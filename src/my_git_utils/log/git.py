"""Small read-only helpers around the git CLI."""

from __future__ import annotations

import re
import subprocess

ANSI = re.compile(r"\x1b\[[0-9;]*m")
HASH = re.compile(r"\b[0-9a-f]{7,40}\b")


def out(*args: str) -> str:
    """stdout of `git <args>`, or "" when git fails."""
    proc = subprocess.run(
        ["git", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    return proc.stdout if proc.returncode == 0 else ""


def ok(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    )


def in_repo() -> bool:
    return ok("rev-parse", "--git-dir")


def commit_of(rev: str) -> str:
    """Full commit id of `rev`, or "" if it does not name a commit."""
    return out("rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}").strip()


def has_object(oid: str) -> bool:
    return ok("cat-file", "-e", f"{oid}^{{commit}}")


def ref_oid(ref: str) -> str:
    return out("rev-parse", "--verify", "--quiet", ref).strip()


def all_refs() -> list[str]:
    return out("for-each-ref", "--format=%(refname)").split()


def remote_urls() -> dict[str, str]:
    """Remote name -> fetch URL."""
    urls: dict[str, str] = {}
    for line in out("config", "--get-regexp", r"^remote\..*\.url$").splitlines():
        key, _, url = line.partition(" ")
        urls[key[len("remote.") : -len(".url")]] = url
    return urls


def symbolic_full_names(rev: str) -> list[str]:
    """Full ref names a revision argument mentions (both ends of A..B, etc.)."""
    names = []
    for line in out("rev-parse", "--symbolic-full-name", rev).splitlines():
        name = line.lstrip("^")
        if name.startswith("refs/") and name not in names:
            names.append(name)
    return names


def upstream_of(branch_ref: str) -> str:
    """Full name of the upstream of refs/heads/<branch>, or ""."""
    short = branch_ref[len("refs/heads/") :]
    name = out("rev-parse", "--symbolic-full-name", f"{short}@{{upstream}}").strip()
    return name if name.startswith("refs/") else ""


def first_hash(line: str) -> str | None:
    match = HASH.search(ANSI.sub("", line))
    return match.group(0) if match else None
