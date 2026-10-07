from __future__ import annotations

from . import git
from .config import Config
from .discovery import worktrees
from .evidence import check_publication
from .model import Audit, Finding, Repository


def inspect(repository: Repository, config: Config, offline: bool) -> Audit:
    audit = Audit(repository)
    try:
        audit.worktrees = worktrees(repository)
    except git.GitError as err:
        audit.findings.append(Finding("Unknown", str(err), unknown=True))
        return audit
    for worktree in audit.worktrees:
        if worktree.bare:
            continue
        if not worktree.exists:
            audit.findings.append(
                Finding("Unknown", f"Missing registered worktree: {worktree.path}", unknown=True)
            )
            continue
        try:
            status = git.run(
                worktree.path, "status", "--porcelain=v1", "-z", "--untracked-files=all"
            )
            if status:
                entries = iter(status.rstrip("\0").split("\0"))
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
            audit.findings.append(Finding("Unknown", str(err), worktree.path, True))
    try:
        stashes = ""
        if git.run(repository.path, "for-each-ref", "refs/stash").strip():
            stashes = git.run(
                repository.path, "reflog", "show", "--format=%gd: %gs", "refs/stash"
            ).strip()
        if stashes:
            audit.findings.append(Finding("Stashes", stashes))

    except git.GitError as err:
        audit.findings.append(Finding("Unknown", str(err), unknown=True))
    check_publication(audit, config, offline)
    return audit
