from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import git
from .config import Config
from .history import recent_repositories
from .model import Repository, Worktree
from .progress import Progress


@dataclass
class Coverage:
    repositories: list[Repository] = field(default_factory=list)
    exclusions: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def worktrees(repository: Repository) -> list[Worktree]:
    records = git.run(repository.path, "worktree", "list", "--porcelain", "-z").split("\0\0")
    result = []
    for record in records:
        fields = dict(line.partition(" ")[::2] for line in record.strip("\0").split("\0") if line)
        if "worktree" in fields:
            result.append(
                Worktree(
                    Path(fields["worktree"]).resolve(),
                    fields.get("branch", "detached HEAD").removeprefix("refs/heads/"),
                    fields.get("HEAD", ""),
                    "bare" in fields,
                )
            )
    return result


def discover(config: Config, progress: Progress | None = None) -> Coverage:
    coverage = Coverage()
    visits, coverage.errors = recent_repositories()
    candidates: list[Path] = list(visits)
    directories = 0
    for index, root in enumerate(config.roots, 1):
        if progress:
            progress.discovered(
                f"root {index}/{len(config.roots)}: {root}", directories, len(candidates)
            )
        if not root.exists():
            if root in config.required_roots:
                coverage.errors.append(f"scan root does not exist: {root}")
            continue
        if not root.is_dir():
            coverage.errors.append(f"scan root is not a directory: {root}")
            continue
        for directory, children, files in os.walk(
            root, followlinks=False, onerror=lambda e: coverage.errors.append(str(e))
        ):
            directories += 1
            # os.walk already classified the entries; avoid two stat calls and
            # several Path objects for every directory in large project trees.
            ordinary = ".git" in children or ".git" in files
            bare = "HEAD" in files and "config" in files and "objects" in children
            children[:] = sorted(c for c in children if c not in {".git", ".venv", "node_modules"})
            if ordinary or bare:
                candidates.append(Path(directory))
            if bare:
                children[:] = [
                    c for c in children if c not in {"objects", "refs", "logs", "hooks", "info"}
                ]
            if progress and directories % 512 == 0:
                progress.discovered(
                    f"root {index}/{len(config.roots)}: {directory}", directories, len(candidates)
                )
    if progress:
        progress.discovered("grouping repository paths", directories, len(candidates))
    repositories: dict[Path, Repository] = {}
    excluded: set[Path] = set()
    for path in dict.fromkeys(candidates + config.exclude):
        try:
            common = Path(
                git.run(
                    path, "rev-parse", "--path-format=absolute", "--git-common-dir"
                ).removesuffix("\n")
            ).resolve()
        except git.GitError as err:
            coverage.errors.append(f"{path}: {err}")
            continue
        if path.resolve() in config.exclude:
            excluded.add(common)
        if common not in repositories:
            repositories[common] = Repository(common, path)
        if path in visits:
            repositories[common].visits.append(path)
    coverage.repositories = [r for c, r in repositories.items() if c not in excluded]
    coverage.exclusions = sorted(excluded)
    return coverage
