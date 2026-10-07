from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .choose import choose
from .config import load
from .discovery import discover
from .progress import Progress
from .report import report
from .scan import inspect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit local Git work in lazygit's recent repositories "
        "for preservation on GitHub."
    )
    parser.add_argument("--all", action="store_true", help="include repositories with no findings")
    parser.add_argument("--offline", action="store_true", help="use cached remote evidence")
    parser.add_argument(
        "--choose", action="store_true", help="choose worktrees to review in lazygit"
    )
    parser.add_argument(
        "--config", type=Path, metavar="PATH", help="personal audit TOML configuration"
    )
    parser.add_argument("--quiet", action="store_true", help="suppress live progress on stderr")
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
    except ValueError as err:
        print(f"git-unsynced: {err}", file=sys.stderr)
        return 2
    if args.choose:
        missing = [tool for tool in ("fzf", "lazygit") if not shutil.which(tool)]
        if missing:
            print(f"git-unsynced: --choose requires {', '.join(missing)}", file=sys.stderr)
            return 1
    if not shutil.which("git"):
        print("git-unsynced: Git is required", file=sys.stderr)
        return 1
    with Progress(enabled=not args.quiet) as progress:
        coverage = discover(config, progress)
        progress.scanning(len(coverage.repositories))
        results = {}
        with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
            futures = {
                executor.submit(inspect, repository, config, args.offline, progress): repository
                for repository in coverage.repositories
            }
            for future in as_completed(futures):
                repository = futures[future]
                results[str(repository.common)] = future.result()
                progress.finished(repository)
        audits = [results[str(r.common)] for r in coverage.repositories]
    report(audits, coverage, args.all, args.offline, config)
    if args.choose:
        try:
            choose(audits, coverage, config, args.all, args.offline, not args.quiet)
        except (OSError, ValueError) as err:
            print(f"git-unsynced: {err}", file=sys.stderr)
            return 1
    return int(bool(coverage.errors or any(a.unknowns for a in audits)))


if __name__ == "__main__":
    sys.exit(main())
