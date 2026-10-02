from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


def commit(cwd: Path, message: str) -> str:
    git(cwd, "commit", "-q", "--allow-empty", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No user git config or tool config leaks into a test."""
    config = tmp_path / "log.toml"
    monkeypatch.setenv("MY_GIT_UTILS_LOG_CONFIG", str(config))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    return config


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A repo with main, feature (tracking vk/feature), release/1.0 and three remotes.

    main ── base ─┬─ feat        (feature, vk/feature)
                  ├─ rel         (release/1.0, vk/release/1.0)
                  └─ other       (other/topic)
    """
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    shas = {"base": commit(path, "base")}
    git(path, "switch", "-q", "-c", "release/1.0")
    shas["rel"] = commit(path, "rel")
    git(path, "switch", "-q", "-c", "topic", "main")
    shas["other"] = commit(path, "other")
    git(path, "switch", "-q", "-c", "feature", "main")
    shas["feat"] = commit(path, "feat")
    for remote in ("origin", "vk", "other"):
        git(path, "remote", "add", remote, f"https://github.com/example/{remote}.git")
    git(path, "update-ref", "refs/remotes/origin/main", shas["base"])
    git(path, "update-ref", "refs/remotes/vk/feature", shas["feat"])
    git(path, "update-ref", "refs/remotes/vk/release/1.0", shas["rel"])
    git(path, "update-ref", "refs/remotes/other/topic", shas["other"])
    git(path, "branch", "-q", "-D", "topic")
    git(path, "config", "branch.feature.remote", "vk")
    git(path, "config", "branch.feature.merge", "refs/heads/feature")
    monkeypatch.chdir(path)
    shas["path"] = str(path)
    return shas


@pytest.fixture
def stub_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory first on PATH for fake executables (gh, fzf)."""
    path = tmp_path / "bin"
    path.mkdir()
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ['PATH']}")
    return path
