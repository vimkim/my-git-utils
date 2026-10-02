from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import commit, git

from my_git_utils.log import pr

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def fake_gh(bin_dir: Path, payload: dict | None, error: str = "no pull requests found") -> None:
    script = bin_dir / "gh"
    if payload is None:
        script.write_text(f"#!/bin/sh\necho '{error}' >&2\nexit 1\n")
    else:
        script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(payload)}\nEOF\n")
    script.chmod(0o755)


def github_remotes(tmp_path: Path, repo: dict[str, str]) -> dict[str, str]:
    """Bare `upstream` (CUBRID/cubrid) and `fork` (me/cubrid) repos reached through
    github.com URLs, with commits the local clone has not fetched yet."""
    local = Path(repo["path"])
    shas = {}
    for name, slug in (("upstream", "CUBRID/cubrid"), ("fork", "me/cubrid")):
        bare = tmp_path / f"{name}.git"
        git(tmp_path, "clone", "-q", "--bare", str(local), str(bare))
        url = f"https://github.com/{slug}.git"
        git(local, "remote", "add", name, url)
        git(local, "config", f"url.{bare}.insteadOf", url)
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(tmp_path / "upstream.git"), str(work))
    git(work, "switch", "-q", "main")
    shas["base"] = commit(work, "develop moved")
    git(work, "push", "-q", "origin", "main")
    git(work, "switch", "-q", "feature")
    shas["head"] = commit(work, "pushed later")
    git(work, "push", "-q", str(tmp_path / "fork.git"), "feature")
    return shas


def payload(shas: dict[str, str], head_owner: str = "me") -> dict:
    return {
        "number": 7,
        "url": "https://github.com/CUBRID/cubrid/pull/7",
        "baseRefName": "main",
        "baseRefOid": shas["base"],
        "headRefName": "feature",
        "headRefOid": shas["head"],
        "headRepository": {"name": "cubrid"},
        "headRepositoryOwner": {"login": head_owner},
    }


def test_pr_fetches_and_marks_head_pr_head_and_base(repo, tmp_path, stub_bin, capsys):
    shas = github_remotes(tmp_path, repo)
    fake_gh(stub_bin, payload(shas))
    assert pr.main([]) == 0
    out = ANSI.sub("", capsys.readouterr().out)
    assert re.search(r"pushed later .*◀ PR-HEAD", out)
    assert re.search(r"develop moved .*◀ PR-BASE", out)
    assert re.search(r"feat .*◀ HEAD", out)
    assert "fork/feature" in out and "upstream/main" in out
    assert git(Path(repo["path"]), "rev-parse", "refs/remotes/fork/feature") == shas["head"]


def test_pr_without_head_remote_uses_pull_ref(repo, tmp_path, stub_bin, capsys):
    shas = github_remotes(tmp_path, repo)
    upstream = tmp_path / "upstream.git"
    git(tmp_path / "work", "push", "-q", str(upstream), f"{shas['head']}:refs/pull/7/head")
    fake_gh(stub_bin, payload(shas, head_owner="stranger"))
    assert pr.main([]) == 0
    out = ANSI.sub("", capsys.readouterr().out)
    assert "upstream/pr/7" in out
    assert re.search(r"pushed later .*◀ PR-HEAD", out)


def test_no_fetch_when_refs_are_current(repo, tmp_path, stub_bin, monkeypatch, capsys):
    shas = github_remotes(tmp_path, repo)
    fake_gh(stub_bin, payload(shas))
    assert pr.main([]) == 0
    capsys.readouterr()
    calls = []
    real_run = pr.subprocess.run
    monkeypatch.setattr(
        pr.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or real_run(cmd, **kw)
    )
    assert pr.main([]) == 0
    assert not any(c[:2] == ["git", "fetch"] for c in calls)


def test_no_pr_falls_back_to_head_upstream_and_default(repo, stub_bin, capsys):
    git(Path(repo["path"]), "symbolic-ref", "refs/remotes/vk/HEAD", "refs/remotes/origin/main")
    fake_gh(stub_bin, None)
    assert pr.main([]) == 0
    captured = capsys.readouterr()
    out = ANSI.sub("", captured.out)
    assert "no pull requests found" in captured.err
    assert re.search(r"feat .*◀ HEAD UPSTREAM", out)
    assert re.search(r"base .*◀ DEFAULT", out)


def test_rejects_two_selectors(repo, stub_bin):
    fake_gh(stub_bin, None)
    assert pr.main(["1", "2"]) == 2


def test_stale_base_oid_marks_tracking_tip_without_fetching(
    repo, tmp_path, stub_bin, monkeypatch, capsys
):
    shas = github_remotes(tmp_path, repo)
    fake_gh(stub_bin, payload(shas))
    assert pr.main([]) == 0
    capsys.readouterr()
    # GitHub reports the base as of the PR's last update: an older commit.
    fake_gh(stub_bin, {**payload(shas), "baseRefOid": repo["base"]})
    calls = []
    real_run = pr.subprocess.run
    monkeypatch.setattr(
        pr.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or real_run(cmd, **kw)
    )
    assert pr.main([]) == 0
    out = ANSI.sub("", capsys.readouterr().out)
    assert re.search(r"develop moved .*◀ PR-BASE", out)
    assert not any(c[:2] == ["git", "fetch"] for c in calls)
