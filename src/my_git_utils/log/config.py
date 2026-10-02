"""Hidden-ref filters: ~/.config/my-git-utils/log.toml plus CLI additions.

    hide    = ["^release"]       # regexes on the branch name without its remote
    remotes = ["vk", "origin"]   # keep-list; refs of other remotes are hidden

Set MY_GIT_UTILS_LOG_CONFIG to read another file.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import git


def config_path() -> Path:
    env = os.environ.get("MY_GIT_UTILS_LOG_CONFIG")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "my-git-utils" / "log.toml"


@dataclass
class Filters:
    hide: list[str] = field(default_factory=list)
    remotes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Filters:
        path = path or config_path()
        try:
            data = tomllib.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        except (OSError, tomllib.TOMLDecodeError) as err:
            print(f"my-git-utils: ignoring {path}: {err}", file=sys.stderr)
            return cls()
        return cls(
            hide=[str(p) for p in data.get("hide", [])],
            remotes=[str(r) for r in data.get("remotes", [])],
        )

    def hidden_refs(self, refs: list[str], remotes: list[str]) -> set[str]:
        """The subset of `refs` these filters hide.

        `remotes` are the repository's remote names. When none of them is on
        the keep-list, no remote is hidden (the keep-list targets other repos).
        """
        patterns = [re.compile(p) for p in self.hide]
        kept = set(self.remotes) & set(remotes)
        # Longest first, so a remote named "a/b" wins over "a".
        by_length = sorted(remotes, key=len, reverse=True)
        hidden = set()
        for ref in refs:
            if ref.startswith("refs/heads/"):
                remote, branch = None, ref[len("refs/heads/") :]
            elif ref.startswith("refs/remotes/"):
                rest = ref[len("refs/remotes/") :]
                remote = next((r for r in by_length if rest.startswith(r + "/")), None)
                if remote is None:
                    continue
                branch = rest[len(remote) + 1 :]
            else:
                continue
            if remote is not None and kept and remote not in kept:
                hidden.add(ref)
            elif any(p.search(branch) for p in patterns):
                hidden.add(ref)
        return hidden


def hidden_refs(filters: Filters, keep: set[str] = frozenset()) -> set[str]:
    """Refs of the current repository hidden by `filters`, minus `keep`."""
    if not filters.hide and not filters.remotes:
        return set()
    return filters.hidden_refs(git.all_refs(), list(git.remote_urls())) - set(keep)
