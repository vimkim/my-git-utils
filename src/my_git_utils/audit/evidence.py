"""Publication evidence lives in a disposable Git directory, never local refs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from . import git
from .config import Config
from .model import Audit, Finding
from .urls import Destination, cached_refs, destinations


@dataclass
class History:
    prefixes: list[str] = field(default_factory=list)
    tags: set[tuple[str, str]] = field(default_factory=set)
    incomplete: bool = False
    shallow: bool = False


def prepare_directory(audit: Audit, directory: Path) -> None:
    repository = audit.repository
    object_format = git.run(repository.path, "rev-parse", "--show-object-format").strip()
    git.run(
        directory,
        "init",
        "-q",
        "--bare",
        "--template=",
        f"--object-format={object_format}",
        isolated=True,
    )
    (directory / "objects/info/alternates").write_bytes(
        (json.dumps(str(repository.common / "objects"), ensure_ascii=False) + "\n").encode(
            errors="surrogateescape"
        )
    )
    # URLs are already effective. Copy connection settings without applying
    # URL rewrites again or importing the original repository's ref mappings.
    for entry in git.run(repository.path, "config", "--null", "--list").split("\0"):
        key, _, value = entry.partition("\n")
        if (
            key.startswith(("credential.", "http.", "https.", "protocol."))
            or key == "core.gitproxy"
        ):
            git.run(directory, "config", "--add", key, value, isolated=True)


def remote_history(
    audit: Audit,
    directory: Path,
    targets: list[Destination],
    config: Config,
    offline: bool,
    history: History,
) -> None:
    for index, target in enumerate(targets):
        checked = False
        for route, url in enumerate(target.urls if not offline else ["cached"]):
            prefix = f"refs/audit/{index}/{route}"
            try:
                if offline:
                    cached = cached_refs(audit.repository.path, target)
                    if not cached:
                        raise git.GitError("cached remote histories unavailable")
                    cached_tags = set()
                    for ref_index, (oid, name) in enumerate(cached):
                        git.run(
                            directory,
                            "update-ref",
                            f"{prefix}/cache/{ref_index}",
                            oid,
                            isolated=True,
                        )
                        if name.startswith("refs/tags/"):
                            cached_tags.add((name.removeprefix("refs/tags/"), oid))
                    history.tags.update(cached_tags)
                else:
                    git.run(
                        directory,
                        "-c",
                        "fetch.fsckObjects=true",
                        "fetch",
                        "--quiet",
                        "--no-tags",
                        "--no-write-fetch-head",
                        "--refmap=",
                        "--no-recurse-submodules",
                        *(["--depth=1"] if history.shallow else []),
                        url,
                        f"+refs/heads/*:{prefix}/heads/*",
                        f"+refs/tags/*:{prefix}/tags/*",
                        timeout=config.timeout,
                        isolated=True,
                    )
                refs = git.run(
                    directory,
                    "for-each-ref",
                    "--format=%(objectname) %(refname)",
                    prefix,
                    isolated=True,
                ).splitlines()
                history.prefixes.append(prefix)
                history.shallow |= (directory / "shallow").exists()
                for ref in refs:
                    oid, name = ref.split(" ", 1)
                    if name.startswith(prefix + "/tags/"):
                        history.tags.add((name.removeprefix(prefix + "/tags/"), oid))
                checked = True
                break
            except git.GitError as err:
                audit.findings.append(Finding("Unknown", f"{target.identity}: {err}"))
        if not checked:
            history.incomplete = True


def local_tips(audit: Audit) -> list[tuple[str, str, Path | None]]:
    checked = {w.branch: w.path for w in audit.worktrees if w.inspected}
    tips = []
    for line in git.run(
        audit.repository.path,
        "for-each-ref",
        "--format=%(objectname) %(refname:strip=2)",
        "refs/heads/",
    ).splitlines():
        oid, name = line.split(" ", 1)
        tips.append((name, oid, checked.get(name)))
    tips += [
        ("detached HEAD", w.head, w.path)
        for w in audit.worktrees
        if w.inspected and w.branch == "detached HEAD" and w.head.strip("0")
    ]
    return tips


def check_publication(audit: Audit, config: Config, offline: bool) -> None:
    path = audit.repository.path
    try:
        targets, errors = destinations(path)
        audit.findings.extend(Finding("Unknown", error) for error in errors)
        if not targets:
            if not errors:
                audit.findings.append(
                    Finding("No GitHub remote", "No configured GitHub destination")
                )
            return
        history = History(
            incomplete=bool(errors),
            shallow=git.run(path, "rev-parse", "--is-shallow-repository").strip() == "true",
        )
        with TemporaryDirectory(prefix="git-unsynced-") as temporary:
            directory = Path(temporary)
            prepare_directory(audit, directory)
            remote_history(audit, directory, targets, config, offline, history)
            for name, oid, worktree_path in local_tips(audit):
                try:
                    count = int(
                        git.run(
                            directory,
                            "rev-list",
                            "--count",
                            oid,
                            "--not",
                            *(f"--glob={p}/*" for p in history.prefixes),
                            isolated=True,
                        )
                    )
                    if count:
                        uncertain = history.incomplete or history.shallow
                        audit.findings.append(
                            Finding(
                                "Unknown" if uncertain else "Local commits need review",
                                f"{name}: publication inconclusive"
                                if uncertain
                                else f"{name}: {count} commit" + ("s" if count != 1 else ""),
                                worktree_path,
                            )
                        )
                except git.GitError as err:
                    audit.findings.append(
                        Finding(
                            "Unknown", f"{name}: publication inconclusive ({err})", worktree_path
                        )
                    )
            for tag in git.run(
                path, "for-each-ref", "--format=%(objectname) %(refname:strip=2)", "refs/tags/"
            ).splitlines():
                oid, name = tag.split(" ", 1)
                if (name, oid) not in history.tags:
                    uncertain = history.incomplete or offline
                    audit.findings.append(
                        Finding(
                            "Unknown" if uncertain else "Unpublished tags",
                            f"{name}: publication inconclusive" if uncertain else name,
                        )
                    )
    except (git.GitError, OSError, ValueError) as err:
        audit.findings.append(Finding("Unknown", str(err)))
