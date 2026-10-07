"""NUL-delimited fzf rows carry JSON paths separately from display text."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .config import Config
from .discovery import Coverage
from .model import Audit
from .report import report
from .scan import inspect


def rows(audits: list[Audit], show_all: bool) -> dict[Path, tuple[Audit, str]]:
    result: dict[Path, tuple[Audit, str]] = {}
    for audit in audits:
        if not audit.findings and not show_all:
            continue
        for worktree in audit.worktrees:
            if not worktree.inspected:
                continue
            findings = [
                f.kind
                for f in audit.findings
                if f.path == worktree.path or (f.path is None and worktree.path == audit.primary)
            ]
            if not findings and not show_all:
                continue
            detail = ", ".join(dict.fromkeys(findings)) or "No findings"
            display = (
                f"{audit.repository.path.name} | {worktree.branch} | "
                f"{str(worktree.path)!r} | {detail}"
            )
            result[worktree.path] = (audit, display)
    return result


def choose(
    audits: list[Audit], coverage: Coverage, config: Config, show_all: bool, offline: bool
) -> None:
    while entries := rows(audits, show_all):
        data = b"".join(
            (json.dumps(str(path)) + "\t" + display + "\0").encode()
            for path, (_, display) in entries.items()
        )
        selection = subprocess.run(
            [
                "fzf",
                "--read0",
                "--print0",
                "--delimiter=\t",
                "--with-nth=2..",
                "--nth=2..",
                "--no-multi",
                "--reverse",
                "--prompt=Review worktree > ",
            ],
            input=data,
            stdout=subprocess.PIPE,
            env={
                **os.environ,
                "FZF_DEFAULT_OPTS": "",
                "FZF_DEFAULT_OPTS_FILE": "",
                "SHELL": "/bin/sh",
            },
        )
        if selection.returncode in (1, 130):
            return
        if selection.returncode:
            raise ValueError(f"fzf exited {selection.returncode}")
        try:
            path = Path(json.loads(selection.stdout.split(b"\t", 1)[0]))
            audit, _ = entries[path]
        except (ValueError, KeyError, TypeError) as err:
            raise ValueError("fzf returned an invalid worktree selection") from err
        opened = subprocess.run(["lazygit", "-p", str(path)])
        updated = inspect(audit.repository, config, offline)
        audits[audits.index(audit)] = updated
        report(audits, coverage, show_all, offline)
        if opened.returncode:
            raise ValueError(f"lazygit exited {opened.returncode}")
    return
