from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Worktree:
    path: Path
    branch: str = "detached HEAD"
    head: str = ""
    bare: bool = False
    inspected: bool = False

    @property
    def exists(self) -> bool:
        return not self.bare and self.path.is_dir()


@dataclass
class Repository:
    common: Path
    path: Path
    visits: list[Path] = field(default_factory=list)


@dataclass
class Finding:
    kind: str
    detail: str
    path: Path | None = None

    @property
    def unknown(self) -> bool:
        return self.kind == "Unknown"


@dataclass
class Audit:
    repository: Repository
    worktrees: list[Worktree] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def primary(self) -> Path | None:
        existing = [w.path for w in self.worktrees if w.inspected]
        if not existing:
            return None
        if self.worktrees[0].path in existing:
            return self.worktrees[0].path
        return next((p for p in self.repository.visits if p in existing), min(existing))

    @property
    def unknowns(self) -> int:
        return sum(f.unknown for f in self.findings)
