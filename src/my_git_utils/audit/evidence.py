"""Publication evidence lives in a disposable Git directory, never local refs."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from . import git
from .config import Config
from .model import Audit, Finding


@dataclass
class Destination:
    identity: str
    url: str
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


def destinations(path: Path) -> tuple[list[Destination], list[str]]:
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
            destination = result.setdefault(identity, Destination(identity, url))
            if remote:
                destination.remotes.add(remote)
        elif "github.com" in url.lower():
            errors.append(f"unresolved GitHub URL identity: {url}")

    for remote in remotes:
        for direction in ([], ["--push"]):
            for url in git.run(path, "remote", "get-url", *direction, "--all", remote).splitlines():
                add(url, remote if not direction else None)
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
        rewrites = [
            (prefix, k[4:-14])
            for k, prefix in entries
            if k.startswith("url.") and k.endswith(".pushinsteadof") and value.startswith(prefix)
        ]
        if key.endswith(".pushremote") and rewrites:
            prefix, replacement = max(rewrites, key=lambda pair: len(pair[0]))
            effective = replacement + value[len(prefix) :]
        else:
            effective = git.run(path, "ls-remote", "--get-url", value).strip()
        add(effective)
    return list(result.values()), errors


def cached_refs(path: Path, target: Destination) -> list[tuple[str, str]]:
    """Use configured fetch mappings; ordinary local heads/tags prove nothing."""
    refs = git.run(path, "for-each-ref", "--format=%(objectname) %(refname)").splitlines()
    result = []
    for remote in target.remotes:
        try:
            mappings = git.run(path, "config", "--get-all", f"remote.{remote}.fetch").splitlines()
        except git.GitError:
            continue
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
                    result.append((oid, remote_ref))
    return result


def check_publication(audit: Audit, config: Config, offline: bool) -> None:
    repository = audit.repository
    path = repository.path
    try:
        targets, errors = destinations(path)
        for error in errors:
            audit.findings.append(Finding("Unknown", error, unknown=True))
        if not targets:
            if not errors:
                audit.findings.append(
                    Finding("No GitHub remote", "No configured GitHub destination")
                )
            return
        branches = git.run(
            path, "for-each-ref", "--format=%(objectname) %(refname:strip=2)", "refs/heads/"
        ).splitlines()
        tags = git.run(
            path, "for-each-ref", "--format=%(objectname) %(refname:strip=2)", "refs/tags/"
        ).splitlines()
        shallow = git.run(path, "rev-parse", "--is-shallow-repository").strip() == "true"
        object_format = git.run(path, "rev-parse", "--show-object-format").strip()
        with TemporaryDirectory(prefix="git-unsynced-") as temporary:
            evidence_path = Path(temporary)
            git.run(
                evidence_path,
                "init",
                "-q",
                "--bare",
                "--template=",
                f"--object-format={object_format}",
            )
            (evidence_path / "objects/info/alternates").write_bytes(
                (json.dumps(str(repository.common / "objects"), ensure_ascii=False) + "\n").encode(
                    errors="surrogateescape"
                )
            )
            verified: list[str] = []
            remote_tags: set[tuple[str, str]] = set()
            incomplete = bool(errors)
            incomplete_history = shallow
            for index, target in enumerate(targets):
                prefix = f"refs/audit/{index}"
                try:
                    if offline:
                        cached = cached_refs(path, target)
                        if not cached:
                            raise git.GitError("cached remote histories unavailable")
                        for oid, name in cached:
                            git.run(
                                evidence_path,
                                "update-ref",
                                prefix + "/" + name.removeprefix("refs/"),
                                oid,
                            )
                    else:
                        git.run(
                            evidence_path,
                            "-c",
                            "fetch.fsckObjects=true",
                            "fetch",
                            "--quiet",
                            "--no-tags",
                            "--no-write-fetch-head",
                            "--refmap=",
                            "--no-recurse-submodules",
                            *(["--depth=1"] if shallow else []),
                            target.url,
                            f"+refs/heads/*:{prefix}/heads/*",
                            f"+refs/tags/*:{prefix}/tags/*",
                            timeout=config.timeout,
                        )
                    refs = git.run(
                        evidence_path, "for-each-ref", "--format=%(objectname) %(refname)", prefix
                    ).splitlines()
                    verified.append(prefix)
                    incomplete_history |= (evidence_path / "shallow").exists()
                    for ref in refs:
                        oid, name = ref.split(" ", 1)
                        if name.startswith(prefix + "/tags/"):
                            remote_tags.add((name.removeprefix(prefix + "/tags/"), oid))
                except git.GitError as err:
                    incomplete = True
                    audit.findings.append(
                        Finding("Unknown", f"{target.identity}: {err}", unknown=True)
                    )
            checked_branches = {w.branch: w.path for w in audit.worktrees if w.exists}
            tips = [
                (
                    line.split(" ", 1)[1],
                    line.split(" ", 1)[0],
                    checked_branches.get(line.split(" ", 1)[1]),
                )
                for line in branches
            ]
            tips += [
                ("detached HEAD", w.head, w.path)
                for w in audit.worktrees
                if w.exists and w.branch == "detached HEAD" and w.head.strip("0")
            ]
            for name, oid, worktree_path in tips:
                try:
                    count = int(
                        git.run(
                            evidence_path,
                            "rev-list",
                            "--count",
                            oid,
                            "--not",
                            *(f"--glob={p}/*" for p in verified),
                        )
                    )
                    if count:
                        uncertain = incomplete or incomplete_history
                        audit.findings.append(
                            Finding(
                                "Unknown" if uncertain else "Local commits need review",
                                f"{name}: publication inconclusive"
                                if uncertain
                                else f"{name}: {count} commit" + ("s" if count != 1 else ""),
                                worktree_path,
                                uncertain,
                            )
                        )
                except git.GitError as err:
                    audit.findings.append(
                        Finding(
                            "Unknown",
                            f"{name}: publication inconclusive ({err})",
                            worktree_path,
                            True,
                        )
                    )
            for tag in tags:
                oid, name = tag.split(" ", 1)
                if (name, oid) not in remote_tags:
                    audit.findings.append(
                        Finding(
                            "Unknown" if incomplete or offline else "Unpublished tags",
                            f"{name}: publication inconclusive" if incomplete or offline else name,
                            unknown=incomplete or offline,
                        )
                    )
    except (git.GitError, OSError, ValueError) as err:
        audit.findings.append(Finding("Unknown", str(err), unknown=True))
