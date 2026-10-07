from __future__ import annotations

from rich.console import Console

from .discovery import Coverage
from .model import Audit

STYLES = {
    "Unknown": "yellow",
    "No GitHub remote": "yellow",
    "Unfinished files": "red",
    "Local commits need review": "red",
    "Unpublished tags": "red",
    "Stashes": "magenta",
}


def report(audits: list[Audit], coverage: Coverage, show_all: bool, offline: bool) -> None:
    console = Console(highlight=False, soft_wrap=True)
    console.print(
        "Local work audit — " + ("cached offline evidence" if offline else "fresh evidence")
    )
    for audit in audits:
        if not audit.findings and not show_all:
            continue
        console.print(str(audit.repository.path), style="bold", markup=False)
        for worktree in audit.worktrees:
            if worktree.exists:
                console.print(f"  {worktree.branch} — {worktree.path}", markup=False)
        if not audit.findings:
            console.print("  No findings", style="green")
        for finding in audit.findings:
            console.print(
                f"  {finding.label}: {finding.detail}",
                style=STYLES.get(finding.label, ""),
                markup=False,
            )
            if finding.path:
                console.print(f"    {finding.path}", markup=False)
    for error in coverage.errors:
        console.print(f"Unknown discovery: {error}", style="yellow", markup=False)
    for excluded in coverage.exclusions:
        console.print(f"Audit exclusion: {excluded}", markup=False)
    console.print(
        f"Repositories: {len(audits) + len(coverage.exclusions)} | Worktrees: "
        f"{sum(w.exists for a in audits for w in a.worktrees)}",
        markup=False,
    )
    console.print(
        f"Projects with findings: {sum(any(not f.unknown for f in a.findings) for a in audits)}"
        f" | Projects with no findings: {sum(not a.findings for a in audits)}"
        f" | Unknown checks: {len(coverage.errors) + sum(a.unknowns for a in audits)}",
        markup=False,
    )
    console.print(
        f"Audit exclusions: {len(coverage.exclusions)} | Missing registered worktrees: "
        f"{sum(not w.exists and not w.bare for a in audits for w in a.worktrees)}",
        markup=False,
    )
    console.print(
        "Coverage: discovered repositories and registered worktrees; ignored files and "
        "reflog-only revisions excluded. Commit identities are compared; equivalent changes "
        "and unconfigured GitHub destinations are outside verification.",
        markup=False,
    )
