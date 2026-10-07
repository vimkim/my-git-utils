from __future__ import annotations

from pathlib import Path

from . import git
from .config import Config
from .discovery import worktrees
from .evidence import check_publication
from .model import Audit, Finding, Repository
from .progress import Progress


def inspect(
    repository: Repository, config: Config, offline: bool, progress: Progress | None = None
) -> Audit:
    audit = Audit(repository)
    if progress:
        progress.task(repository, "worktree registrations")
    try:
        audit.worktrees = worktrees(repository)
    except git.GitError as err:
        audit.findings.append(Finding("Unknown", str(err)))
        return audit
    for index, worktree in enumerate(audit.worktrees, 1):
        if progress:
            progress.task(repository, f"files {index}/{len(audit.worktrees)}: {worktree.path.name}")
        if worktree.bare:
            continue
        if not worktree.exists:
            audit.findings.append(
                Finding("Unknown", f"Missing registered worktree: {worktree.path}")
            )
            continue
        try:
            common = Path(
                git.run(
                    worktree.path, "rev-parse", "--path-format=absolute", "--git-common-dir"
                ).removesuffix("\n")
            ).resolve()
            root = Path(
                git.run(worktree.path, "rev-parse", "--show-toplevel").removesuffix("\n")
            ).resolve()
            if common != repository.common or root != worktree.path:
                raise git.GitError("registered path is not this worktree")
            worktree.inspected = True
            status = git.run(
                worktree.path, "status", "--porcelain=v1", "-z", "--untracked-files=all"
            )
            if status:
                entries = iter(status.rstrip("\x00").split("\x00"))
                files = []
                for entry in entries:
                    if entry[:1] in ("R", "C") or entry[1:2] in ("R", "C"):
                        files.append(f"{entry[:2]} {next(entries)!r} -> {entry[3:]!r}")
                    else:
                        files.append(f"{entry[:2]} {entry[3:]!r}")
                audit.findings.append(
                    Finding(
                        "Unfinished files",
                        f"{len(files)} file(s): " + ", ".join(files),
                        worktree.path,
                    )
                )
        except git.GitError as err:
            audit.findings.append(Finding("Unknown", str(err), worktree.path))
    if progress:
        progress.task(repository, "stashes")
    try:
        stashes = ""
        if git.run(repository.path, "for-each-ref", "refs/stash").strip():
            stashes = git.run(
                repository.path, "reflog", "show", "--format=%gd: %gs", "refs/stash"
            ).strip()
            if not stashes:
                stashes = "Retained refs/stash without a reflog"
        if stashes:
            audit.findings.append(Finding("Stashes", stashes))
    except git.GitError as err:
        audit.findings.append(Finding("Unknown", str(err)))
    repository.path = audit.primary or repository.common
    check_publication(audit, config, offline, progress)
    return audit
