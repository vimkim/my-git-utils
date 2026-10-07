from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


@dataclass
class Config:
    exclude: list[Path]
    timeout: float = 30
    concurrency: int = 4


def load(path: Path | None) -> Config:
    explicit = path is not None
    path = path or config_home() / "my-git-utils/audit.toml"
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        if explicit:
            raise ValueError(f"configuration does not exist: {path}") from None
        data = {}
    except (OSError, ValueError) as err:
        raise ValueError(f"{path}: {err}") from err
    if "roots" in data:
        raise ValueError("roots is no longer supported; audit coverage uses lazygit recentrepos")
    unknown = set(data) - {"exclude", "timeout", "concurrency"}
    if unknown:
        raise ValueError(f"unknown configuration keys: {', '.join(sorted(unknown))}")
    exclude = data.get("exclude", [])
    if not isinstance(exclude, list) or any(not isinstance(p, str) for p in exclude):
        raise ValueError("exclude must be an array of paths")
    timeout = data.get("timeout", 30)
    concurrency = data.get("concurrency", 4)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive number")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency <= 0:
        raise ValueError("concurrency must be a positive integer")
    return Config(
        [Path(p).expanduser().resolve() for p in exclude],
        timeout,
        concurrency,
    )
