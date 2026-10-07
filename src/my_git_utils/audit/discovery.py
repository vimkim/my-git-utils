from __future__ import annotations

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
    registered = {w.path: w for w in result}
    selected: dict[Path, None] = {}
    for visit in repository.visits:
        # History can contain a worktree subdirectory. Prefer an exact
        # registration so a broken nested worktree is still reported unknown.
        path = (
            visit
            if visit in registered
            else Path(git.run(visit, "rev-parse", "--show-toplevel").removesuffix("\n")).resolve()
        )
        selected[path] = None
    if selected.keys() - registered.keys():
        raise git.GitError("recent repository path is not a registered worktree")
    # Audit.primary prefers the first worktree. Keep the main worktree first
    # when listed; otherwise use history order, most recent first.
    paths = list(selected)
    if result and result[0].path in selected:
        paths.remove(result[0].path)
        paths.insert(0, result[0].path)
    return [registered[path] for path in paths]


def discover(config: Config, progress: Progress | None = None) -> Coverage:
    coverage = Coverage()
    visits, coverage.errors = recent_repositories()
    candidates = list(dict.fromkeys(visits))
    if progress:
        progress.discovered("grouping lazygit recent repositories", len(candidates))
    repositories: dict[Path, Repository] = {}
    excluded: set[Path] = set()
    for index, path in enumerate(dict.fromkeys(candidates + config.exclude), 1):
        if progress:
            progress.discovered(f"grouping path {index}: {path}", len(candidates))
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
        if path in visits:
            if common not in repositories:
                repositories[common] = Repository(common, path)
            repositories[common].visits.append(path)
    coverage.repositories = [r for c, r in repositories.items() if c not in excluded]
    coverage.exclusions = sorted(excluded & repositories.keys())
    return coverage
