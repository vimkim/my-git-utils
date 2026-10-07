"""Resolve configured GitHub destinations and their usable transport routes."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import git


@dataclass
class Destination:
    identity: str
    urls: list[str]
    remotes: set[str] = field(default_factory=set)


def github_identity(url: str) -> str | None:
    scp = re.match(r"(?:[^/@:]+@)?github\.com:(.+)", url, re.I)
    if scp:
        slug = scp.group(1)
    else:
        parsed = urlsplit(url)
        if parsed.hostname != "github.com" or parsed.scheme not in ("https", "ssh", "git", "http"):
            return None
        slug = parsed.path.lstrip("/")
    slug = slug.rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", slug):
        return None
    return slug.lower()


def resolve_ssh_identity(url: str) -> str:
    scp = re.match(r"(?:([^/@:]+)@)?([^/:]+):(.+)", url) if "://" not in url else None
    parsed = urlsplit(url) if not scp else None
    if scp:
        user, host, slug = scp.groups()
    elif parsed and parsed.scheme == "ssh":
        user, host, slug = parsed.username, parsed.hostname, parsed.path.lstrip("/")
    else:
        return url
    if not host or host.lower() == "github.com":
        return url
    try:
        proc = subprocess.run(
            ["ssh", "-G", "-o", "BatchMode=yes", "--", f"{user}@{host}" if user else host],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise ValueError(f"unresolved SSH URL identity: {url} ({err})") from err
    hostname = next(
        (
            line.split(" ", 1)[1]
            for line in proc.stdout.splitlines()
            if line.startswith("hostname ")
        ),
        "",
    )
    if proc.returncode or not hostname or "." not in hostname:
        raise ValueError(f"unresolved SSH URL identity: {url}")
    return f"git@{hostname}:{slug}"


def destinations(
    path: Path, keep_remotes: list[str] | None = None
) -> tuple[list[Destination], list[str]]:
    """A keep-list selects named remotes before resolving any of their URLs."""
    result: dict[str, Destination] = {}
    errors: list[str] = []
    remotes = git.run(path, "remote").splitlines()

    def add(url: str, remote: str | None = None) -> None:
        try:
            identity = github_identity(resolve_ssh_identity(url))
        except ValueError as err:
            if str(err) not in errors:
                errors.append(str(err))
            return
        if identity:
            destination = result.setdefault(identity, Destination(identity, []))
            if url not in destination.urls:
                destination.urls.append(url)
            if remote:
                destination.remotes.add(remote)
        elif "github.com" in url.lower():
            errors.append(f"unresolved GitHub URL identity: {url}")

    for remote in remotes:
        if keep_remotes is not None and remote not in keep_remotes:
            continue
        for direction in ([], ["--push"]):
            for url in git.run(path, "remote", "get-url", *direction, "--all", remote).splitlines():
                add(url, remote if not direction else None)
    if keep_remotes is not None:
        return list(result.values()), errors
    entries = [
        entry.partition("\n")[::2]
        for entry in git.run(path, "config", "--null", "--list").split("\0")
        if entry
    ]
    for key, value in entries:
        if not (key.startswith("branch.") and key.endswith((".remote", ".pushremote"))):
            continue
        if value in remotes or value == ".":
            continue
        fetch_url = git.run(path, "ls-remote", "--get-url", value).strip()
        if key.endswith(".remote"):
            add(fetch_url)
        rewrites = [
            (prefix, k[4:-14])
            for k, prefix in entries
            if k.startswith("url.") and k.endswith(".pushinsteadof") and value.startswith(prefix)
        ]
        if rewrites:
            prefix, replacement = max(rewrites, key=lambda pair: len(pair[0]))
            push_url = replacement + value[len(prefix) :]
        else:
            push_url = fetch_url
        add(push_url)
    return list(result.values()), errors


def cached_refs(path: Path, target: Destination) -> list[tuple[str, str]]:
    """Use configured fetch mappings; ordinary local heads/tags prove nothing."""
    refs = git.run(path, "for-each-ref", "--format=%(objectname) %(refname)").splitlines()
    result = []
    for remote in sorted(target.remotes):
        try:
            mappings = git.run(path, "config", "--get-all", f"remote.{remote}.fetch").splitlines()
        except git.GitError:
            continue
        exclusions = [mapping[1:] for mapping in mappings if mapping.startswith("^")]
        for mapping in mappings:
            source, separator, destination = mapping.lstrip("+").partition(":")
            if not separator or not source.startswith(("refs/heads/", "refs/tags/")):
                continue
            if destination.startswith(("refs/heads/", "refs/tags/")):
                continue
            pattern = "^" + re.escape(destination).replace(r"\*", "(.*)") + "$"
            for ref in refs:
                oid, name = ref.split(" ", 1)
                match = re.match(pattern, name)
                if match:
                    remote_ref = source.replace("*", match.group(1)) if "*" in source else source
                    if not any(fnmatch.fnmatchcase(remote_ref, pattern) for pattern in exclusions):
                        result.append((oid, remote_ref))
    return result
