"""Read lazygit's visit history; a missing state file is normal."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .config import config_home


def recent_repositories() -> tuple[list[Path], list[str]]:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    for path in (state / "lazygit/state.yml", config_home() / "lazygit/state.yml"):
        try:
            data = yaml.safe_load(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError, yaml.YAMLError) as err:
            return [], [f"lazygit history {path}: {err}"]
        if data is None:
            return [], []
        if not isinstance(data, dict):
            return [], [f"lazygit history {path}: expected a YAML mapping"]
        entries = data.get("recentrepos", [])
        if not isinstance(entries, list) or any(not isinstance(p, str) for p in entries):
            return [], [f"lazygit history {path}: recentrepos must be an array of paths"]
        return [Path(p).expanduser().resolve() for p in entries], []
    return [], []
