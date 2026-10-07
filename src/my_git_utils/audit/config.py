from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


@dataclass
class Config:
    roots: list[Path]
    exclude: list[Path]
    timeout: float = 30
    concurrency: int = 4
    required_roots: list[Path] = field(default_factory=list)


def load(path: Path | None, extra_roots: list[str]) -> Config:
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
    unknown = set(data) - {"roots", "exclude", "timeout", "concurrency"}
    if unknown:
        raise ValueError(f"unknown configuration keys: {', '.join(sorted(unknown))}")
    defaults = [str(Path.home() / name) for name in ("gh", "temp", "tmp")]
    for key in ("roots", "exclude"):
        value = data.get(key, defaults if key == "roots" else [])
        if not isinstance(value, list) or any(not isinstance(p, str) for p in value):
            raise ValueError(f"{key} must be an array of paths")
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
        [Path(p).expanduser().absolute() for p in data.get("roots", defaults) + extra_roots],
        [Path(p).expanduser().resolve() for p in data.get("exclude", [])],
        timeout,
        concurrency,
        [Path(p).expanduser().absolute() for p in data.get("roots", []) + extra_roots],
    )
