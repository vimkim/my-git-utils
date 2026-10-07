from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import commit, git


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("NO_COLOR", "1")
    root = home / "gh"
    root.mkdir()
    return home, root


def repository(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    commit(path, "base")
    return path


def run_audit(*args: str):
    return subprocess.run(["git-unsynced", *args], text=True, capture_output=True, timeout=20)


def test_discovers_registered_worktrees_and_unfinished_files(audit_env, tmp_path):
    _, root = audit_env
    path = repository(root / ".hidden" / "project")
    linked = tmp_path / "outside root"
    git(path, "worktree", "add", "-q", "-b", "topic", str(linked))
    (path / "todo.txt").write_text("work")
    (linked / "other.txt").write_text("other work")
    (linked / ".gitignore").write_text("ignored\n")
    (linked / "ignored").write_text("ignored output")
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No GitHub remote" in result.stdout
    assert str(linked) in result.stdout and str(path) in result.stdout
    assert "todo.txt" in result.stdout and "other.txt" in result.stdout
    assert "ignored output" not in result.stdout
    assert "Repositories: 1" in result.stdout and "Worktrees: 2" in result.stdout
    assert "\x1b[" not in result.stdout


def test_history_deduplication_project_exclusion_and_missing_registration(audit_env, tmp_path):
    home, root = audit_env
    path = repository(root / "project")
    linked = tmp_path / "linked"
    missing = tmp_path / "missing"
    git(path, "worktree", "add", "-q", "-b", "linked", str(linked))
    git(path, "worktree", "add", "-q", "-b", "missing", str(missing))
    import shutil

    shutil.rmtree(missing)
    history_repo = repository(tmp_path / "history only")
    history = home / ".local/state/lazygit/state.yml"
    history.parent.mkdir(parents=True)
    history.write_text(f"recentrepos:\n  - {linked}\n  - {history_repo}\n  - {path}\n")
    config = home / "audit.toml"
    config.write_text(f'exclude = ["{linked}"]\n')
    result = run_audit("--config", str(config))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repositories: 2" in result.stdout and "Audit exclusions: 1" in result.stdout
    assert str(history_repo) in result.stdout
    assert "Worktrees: 1" in result.stdout
    config.write_text("exclude = []\n")
    result = run_audit("--config", str(config))
    assert result.returncode == 1, result.stderr
    assert "Missing registered worktrees: 1" in result.stdout
    assert str(missing) in result.stdout


@pytest.fixture
def remote_transport(stub_bin, monkeypatch):
    import json
    import shutil

    real_git = shutil.which("git")
    wrapper = stub_bin / "git"
    wrapper.write_text("""#!/usr/bin/env python3
import json, os, subprocess, sys, time
args = sys.argv[1:]
if 'fetch' in args:
    if 'AUDIT_REQUIRE_HEADER' in os.environ:
        gitdir = args[args.index('-C') + 1]
        value = subprocess.check_output([os.environ['AUDIT_TEST_GIT'], '-C', gitdir,
                                         'config', '--get', 'http.extraHeader']).decode().strip()
        assert value == os.environ['AUDIT_REQUIRE_HEADER']
    remotes = json.loads(os.environ['AUDIT_TEST_REMOTES'])
    for i, arg in enumerate(args):
        if arg in remotes:
            target = remotes[arg]
            if target == 'FAIL':
                print('test remote unavailable', file=sys.stderr)
                sys.exit(1)
            if target == 'TIMEOUT':
                time.sleep(10)
            args[i] = target
            break
if 'fetch' in args and 'AUDIT_FETCH_EVENTS' in os.environ:
    def event(kind):
        descriptor = os.open(os.environ['AUDIT_FETCH_EVENTS'],
                             os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.write(descriptor, f'{os.getpid()} {kind}\\n'.encode())
        os.close(descriptor)
    event('start')
    time.sleep(0.2)
    result = subprocess.call([os.environ['AUDIT_TEST_GIT'], *args])
    event('end')
    sys.exit(result)
os.execv(os.environ['AUDIT_TEST_GIT'], [os.environ['AUDIT_TEST_GIT'], *args])
""")
    wrapper.chmod(0o755)
    monkeypatch.setenv("AUDIT_TEST_GIT", real_git)
    destinations = {}
    monkeypatch.setenv("AUDIT_TEST_REMOTES", "{}")

    def add(path, name, remote):
        url = f"https://github.com/test/{name}.git"
        git(path, "remote", "add", name, url)
        destinations[url] = str(remote)
        monkeypatch.setenv("AUDIT_TEST_REMOTES", json.dumps(destinations))
        return url

    return add


def test_fresh_publication_in_any_remote_and_local_state_preservation(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / "project")
    origin = tmp_path / "origin.git"
    fork = tmp_path / "fork.git"
    git(path, "clone", "-q", "--bare", str(path), str(origin))
    git(path, "clone", "-q", "--bare", str(path), str(fork))
    remote_transport(path, "origin", origin)
    remote_transport(path, "fork", fork)
    git(path, "switch", "-q", "-c", "unpublished")
    topic = commit(path, "local topic")
    git(path, "tag", "-a", "v1", "-m", "local annotation")
    git(path, "switch", "-q", "main")
    detached = tmp_path / "detached"
    git(path, "worktree", "add", "-q", "--detach", str(detached))
    detached_head = commit(detached, "detached work")
    (path / "file").write_text("staged")
    git(path, "add", "file")
    (path / "file").write_text("unstaged")
    (path / ".git/FETCH_HEAD").write_text("preserve me\n")
    before_refs = git(path, "show-ref")
    before_index = (path / ".git/index").read_bytes()
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local commits need review: unpublished: 1 commit" in result.stdout
    assert "Local commits need review: detached HEAD: 1 commit" in result.stdout
    assert "Unpublished tags: v1" in result.stdout
    assert git(path, "show-ref") == before_refs
    assert (path / ".git/index").read_bytes() == before_index
    assert (path / ".git/FETCH_HEAD").read_text() == "preserve me\n"
    assert (path / "file").read_text() == "unstaged"
    git(
        path,
        "push",
        "-q",
        str(fork),
        f"{topic}:refs/heads/topic",
        f"{detached_head}:refs/heads/detached",
        "refs/tags/v1",
    )
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local commits need review" not in result.stdout
    assert "Unpublished tags" not in result.stdout
    assert git(path, "show-ref") == before_refs


def test_annotated_tag_identity_name_collisions_and_remote_deletion(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / "project")
    git(path, "tag", "-a", "v1", "-m", "remote annotation")
    git(path, "tag", "light")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "origin", remote)
    git(path, "tag", "-f", "-a", "v1", "-m", "different local annotation")
    git(path, "tag", "another-name")
    git(remote, "update-ref", "-d", "refs/tags/light")
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("v1", "light", "another-name"):
        assert f"Unpublished tags: {name}" in result.stdout
    assert "Local commits need review" not in result.stdout


def test_failed_remote_retains_positive_evidence_and_makes_absence_unknown(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "good", remote)
    remote_transport(path, "bad", "FAIL")
    git(path, "switch", "-q", "-c", "local")
    commit(path, "local work")
    git(path, "tag", "local-tag")
    # Stale information must not turn the failed fresh refresh into success.
    git(path, "update-ref", "refs/remotes/bad/local", git(path, "rev-parse", "HEAD"))
    result = run_audit()
    assert result.returncode == 1, result.stderr
    assert "Unknown: test/bad:" in result.stdout
    assert "local: publication inconclusive" in result.stdout
    assert "local-tag: publication inconclusive" in result.stdout
    assert "main: publication inconclusive" not in result.stdout
    assert "Local commits need review" not in result.stdout
    assert "Unpublished tags" not in result.stdout


def test_offline_uses_cached_histories_without_fetching(audit_env, remote_transport):
    _, root = audit_env
    path = repository(root / "project")
    remote_transport(path, "origin", "FAIL")
    git(path, "update-ref", "refs/remotes/origin/main", git(path, "rev-parse", "HEAD"))
    commit(path, "local work")
    result = run_audit("--offline")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cached offline evidence" in result.stdout
    assert "Local commits need review: main: 1 commit" in result.stdout
    git(path, "tag", "unconfirmed-tag")
    result = run_audit("--offline")
    assert result.returncode == 1, result.stderr
    assert "unconfirmed-tag: publication inconclusive" in result.stdout
    assert "Unpublished tags" not in result.stdout


def test_explicit_branch_destination_rewrites_and_push_urls(
    audit_env, tmp_path, remote_transport, monkeypatch
):
    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    url = remote_transport(path, "fork", remote)
    git(path, "remote", "remove", "fork")
    git(path, "config", "url.https://github.com/test/.insteadOf", "review:")
    git(path, "config", "branch.main.pushRemote", "review:fork.git")
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout and "No GitHub remote" not in result.stdout
    # Named remote's separate push URL is also a configured GitHub destination.
    git(path, "config", "--unset", "branch.main.pushRemote")
    git(path, "remote", "add", "local", str(tmp_path / "local.git"))
    git(path, "remote", "set-url", "--push", "local", url)
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout


def test_chooser_exact_path_and_return_refresh_loop(audit_env, tmp_path, stub_bin, monkeypatch):
    import json

    _, root = audit_env
    path = repository(root / "project")
    linked = tmp_path / "linked \t worktree\nwith [markup]"
    git(path, "worktree", "add", "-q", "-b", "topic", str(linked))
    (linked / "todo").write_text("unfinished")
    log = tmp_path / "chooser.json"
    monkeypatch.setenv("AUDIT_CHOOSER_LOG", str(log))
    monkeypatch.setenv("AUDIT_CHOOSER_PATH", str(linked))
    fzf = stub_bin / "fzf"
    fzf.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ['AUDIT_CHOOSER_LOG'])
rows = sys.stdin.buffer.read().split(b'\\0')
previous = json.loads(log.read_text()) if log.exists() else []
previous.append([r.decode() for r in rows if r])
log.write_text(json.dumps(previous))
if len(previous) > 1:
    assert all('Unfinished files' not in r for r in previous[-1])
    sys.exit(130)
for row in rows:
    if row and json.loads(row.split(b'\\t', 1)[0]) == os.environ['AUDIT_CHOOSER_PATH']:
        sys.stdout.buffer.write(row + b'\\0')
        sys.exit(0)
sys.exit(1)
""")
    fzf.chmod(0o755)
    lazygit = stub_bin / "lazygit"
    lazygit.write_text("""#!/usr/bin/env python3
import os, sys
from pathlib import Path
assert sys.argv[1:] == ['-p', os.environ['AUDIT_CHOOSER_PATH']]
(Path(sys.argv[2]) / 'todo').unlink()
""")
    lazygit.chmod(0o755)
    result = run_audit("--choose")
    assert result.returncode == 0, result.stdout + result.stderr
    rounds = json.loads(log.read_text())
    assert len(rounds) == 2
    assert sum("Unfinished files" in r for r in rounds[0]) == 1
    assert all("Unfinished files" not in r for r in rounds[1])


@pytest.mark.parametrize("location", [".local/state", ".config"])
def test_history_locations_and_malformed_history_are_visible(audit_env, tmp_path, location):
    home, root = audit_env
    repository(root / "from-root")
    other = repository(tmp_path / "only-history")
    history = home / location / "lazygit/state.yml"
    history.parent.mkdir(parents=True)
    history.write_text(f'recentrepos: ["{other}"]\n')
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repositories: 2" in result.stdout
    history.write_text("recentrepos: [bad yaml\n")
    result = run_audit()
    assert result.returncode == 1
    assert "Unknown discovery: lazygit history" in result.stdout
    assert "Repositories: 1" in result.stdout


def test_configured_roots_replace_defaults_cli_adds_roots_and_prunes_dependencies(
    audit_env, tmp_path
):
    home, root = audit_env
    repository(root / "default")
    chosen = tmp_path / "chosen"
    repository(chosen / "included")
    repository(chosen / "node_modules" / "dependency")
    repository(chosen / ".venv" / "dependency")
    outside = repository(tmp_path / "outside")
    (chosen / "symlink").symlink_to(outside, target_is_directory=True)
    config = home / "audit.toml"
    config.write_text(f'roots = ["{chosen}"]\n')
    result = run_audit("--config", str(config))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repositories: 1" in result.stdout
    result = run_audit("--config", str(config), "--root", str(chosen / "symlink"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repositories: 2" in result.stdout


def test_shared_stashes_and_independent_tracked_files(audit_env, tmp_path):
    _, root = audit_env
    path = repository(root / "project")
    (path / "file").write_text("base")
    (path / ".gitignore").write_text("ignored\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "files")
    linked = tmp_path / "linked"
    git(path, "worktree", "add", "-q", "-b", "linked", str(linked))
    (path / "file").write_text("stash me")
    git(path, "stash", "push", "-qm", "shared stash")
    (path / "file").write_text("main work")
    (linked / "file").write_text("linked work")
    (linked / "ignored").write_text("ignored")
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Unfinished files:") == 2
    assert result.stdout.count("Stashes:") == 1
    assert "shared stash" in result.stdout
    assert "ignored" not in result.stdout.replace("ignored files", "")


def test_timeout_is_unknown_and_other_repositories_continue(audit_env, tmp_path, remote_transport):
    home, root = audit_env
    timed = repository(root / "timed")
    remote_transport(timed, "timed", "TIMEOUT")
    repository(root / "local-only")
    config = home / "audit.toml"
    config.write_text("timeout = 0.15\n")
    result = run_audit("--config", str(config))
    assert result.returncode == 1
    assert "timed out after 0.15s" in result.stdout
    assert "No GitHub remote" in result.stdout
    assert "Repositories: 2" in result.stdout


def test_shallow_absence_is_inconclusive_and_tip_publication_is_useful(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    source = repository(tmp_path / "source")
    base = git(source, "rev-parse", "HEAD")
    commit(source, "second")
    path = root / "shallow"
    git(source, "clone", "-q", "--depth=1", "file://" + str(source), str(path))
    remote_transport(path, "github", source)
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout
    git(source, "update-ref", "refs/heads/main", base)
    before = (path / ".git/shallow").read_bytes()
    result = run_audit()
    assert result.returncode == 1
    assert "main: publication inconclusive" in result.stdout
    assert "Local commits need review" not in result.stdout
    assert (path / ".git/shallow").read_bytes() == before


def test_missing_local_object_does_not_claim_unpublished_work(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "origin", remote)
    (path / ".git/refs/heads/broken").write_text("a" * 40 + "\n")
    result = run_audit()
    assert result.returncode == 1
    assert "Unknown: broken:" in result.stdout
    assert "Local commits need review: broken" not in result.stdout


def test_default_filters_clean_repositories_all_includes_them_and_behind_is_clean(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / "clean")
    remote = repository(tmp_path / "remote")
    git(remote, "fetch", "-q", str(path), "main")
    git(remote, "reset", "-q", "--hard", "FETCH_HEAD")
    commit(remote, "remote is ahead")
    remote_transport(path, "origin", remote)
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(path) not in result.stdout
    assert "Projects with no findings: 1" in result.stdout
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(path) in result.stdout and "No findings" in result.stdout


def test_ssh_alias_and_unresolved_identity_are_reported(
    audit_env, tmp_path, remote_transport, stub_bin, monkeypatch
):
    import json

    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    url = remote_transport(path, "origin", remote)
    alias = "git@personal-github:test/origin.git"
    git(path, "remote", "set-url", "origin", alias)
    monkeypatch.setenv("AUDIT_TEST_REMOTES", json.dumps({url: str(remote), alias: str(remote)}))
    ssh = stub_bin / "ssh"
    ssh.write_text('#!/bin/sh\nprintf "hostname github.com\\n"\n')
    ssh.chmod(0o755)
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout
    ssh.write_text('#!/bin/sh\nprintf "hostname unresolved-alias\\n"\n')
    result = run_audit()
    assert result.returncode == 1
    assert "unresolved SSH URL identity" in result.stdout


def test_chooser_publishes_unchecked_branch_then_empty_list_finishes(
    audit_env, tmp_path, remote_transport, stub_bin, monkeypatch
):
    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "origin", remote)
    git(path, "switch", "-q", "-c", "unchecked")
    commit(path, "local work")
    git(path, "switch", "-q", "main")
    monkeypatch.setenv("AUDIT_PUBLICATION_REMOTE", str(remote))
    fzf = stub_bin / "fzf"
    fzf.write_text("""#!/usr/bin/env python3
import sys
rows = sys.stdin.buffer.read().split(b'\\0')
assert len([r for r in rows if r]) == 1
assert b'Local commits need review' in rows[0]
sys.stdout.buffer.write(rows[0] + b'\\0')
""")
    fzf.chmod(0o755)
    lazygit = stub_bin / "lazygit"
    lazygit.write_text("""#!/usr/bin/env python3
import os, subprocess, sys
subprocess.run(['git', '-C', sys.argv[2], 'push', '-q',
                os.environ['AUDIT_PUBLICATION_REMOTE'], 'unchecked'], check=True)
""")
    lazygit.chmod(0o755)
    result = run_audit("--choose")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Local commits need review: unchecked") == 1
    assert "Projects with no findings: 1" in result.stdout


def test_fresh_fetch_handles_unusual_primary_path_and_noncommit_tag(
    audit_env, tmp_path, remote_transport
):
    _, root = audit_env
    path = repository(root / 'project "quoted"\n')
    blob = git(path, "hash-object", "-w", "--stdin")
    git(path, "tag", "blob-tag", blob)
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "origin", remote)
    commit(path, "unpublished")
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local commits need review: main: 1 commit" in result.stdout


@pytest.mark.parametrize(
    "config_text",
    [
        'roots = "wrong"',
        "timeout = 0",
        "timeout = inf",
        "concurrency = true",
        "typo = 1",
    ],
)
def test_invalid_configuration_is_a_diagnostic(audit_env, config_text):
    home, _ = audit_env
    config = home / "invalid.toml"
    config.write_text(config_text)
    result = run_audit("--config", str(config))
    assert result.returncode == 2
    assert "git-unsynced:" in result.stderr and "Traceback" not in result.stderr


def test_requested_missing_root_retains_partial_report(audit_env, tmp_path):
    _, root = audit_env
    repository(root / "covered")
    result = run_audit("--root", str(tmp_path / "missing-root"))
    assert result.returncode == 1
    assert "scan root does not exist" in result.stdout
    assert "Repositories: 1" in result.stdout


def test_missing_interactive_tools_are_only_required_for_choose(audit_env, tmp_path):
    import os
    import shutil

    command = shutil.which("git-unsynced")
    git_only = tmp_path / "git-only"
    git_only.mkdir()
    (git_only / "git").symlink_to(shutil.which("git"))
    env = {**os.environ, "PATH": str(git_only)}
    ordinary = subprocess.run([command], capture_output=True, text=True, env=env)
    assert ordinary.returncode == 0
    choosing = subprocess.run([command, "--choose"], capture_output=True, text=True, env=env)
    assert choosing.returncode == 1
    assert "--choose requires fzf, lazygit" in choosing.stderr


def test_handled_failure_preserves_refs_and_removes_temporary_evidence(
    audit_env, tmp_path, remote_transport, monkeypatch
):
    _, root = audit_env
    path = repository(root / "project")
    remote_transport(path, "origin", "FAIL")
    git(path, "tag", "preserved")
    git(path, "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*")
    git(path, "config", "remote.origin.tagOpt", "--tags")
    git(path, "config", "fetch.pruneTags", "true")
    before = git(path, "show-ref")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setenv("TMPDIR", str(evidence))
    result = run_audit()
    assert result.returncode == 1
    assert git(path, "show-ref") == before
    assert list(evidence.iterdir()) == []


def test_repository_without_existing_worktrees_is_reportable_without_picker_target(
    audit_env, tmp_path, stub_bin
):
    home, root = audit_env
    source = repository(tmp_path / "source")
    bare = root / "bare.git"
    git(source, "clone", "-q", "--bare", str(source), str(bare))
    history = home / ".local/state/lazygit/state.yml"
    history.parent.mkdir(parents=True)
    history.write_text(f'recentrepos: ["{bare}"]\n')
    for tool in ("fzf", "lazygit"):
        stub = stub_bin / tool
        stub.write_text("#!/bin/sh\nexit 99\n")
        stub.chmod(0o755)
    result = run_audit("--choose")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repositories: 1" in result.stdout and "Worktrees: 0" in result.stdout
    assert "No GitHub remote" in result.stdout


def test_repository_concurrency_is_bounded_and_configurable(
    audit_env, tmp_path, remote_transport, monkeypatch
):
    home, root = audit_env
    source = repository(tmp_path / "source")
    for index in range(5):
        path = root / str(index)
        git(source, "clone", "-q", str(source), str(path))
        git(path, "remote", "remove", "origin")
        remote_transport(path, f"github-{index}", source)
    events = tmp_path / "events"
    monkeypatch.setenv("AUDIT_FETCH_EVENTS", str(events))

    def peak():
        active, maximum = set(), 0
        for event in events.read_text().splitlines():
            pid, kind = event.split()
            if kind == "start":
                active.add(pid)
                maximum = max(maximum, len(active))
            else:
                active.remove(pid)
        assert not active
        return maximum

    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert 2 <= peak() <= 4
    events.unlink()
    config = home / "audit.toml"
    config.write_text("concurrency = 1\n")
    result = run_audit("--config", str(config))
    assert result.returncode == 0, result.stdout + result.stderr
    assert peak() == 1


@pytest.mark.parametrize("status, expected", [(130, 0), (1, 0), (2, 1)])
def test_chooser_cancellation_and_failure_have_distinct_exit_statuses(
    audit_env, stub_bin, status, expected
):
    _, root = audit_env
    repository(root / "project")
    for tool, code in [("fzf", status), ("lazygit", 99)]:
        stub = stub_bin / tool
        stub.write_text(f"#!/bin/sh\ncat >/dev/null\nexit {code}\n")
        stub.chmod(0o755)
    result = run_audit("--choose")
    assert result.returncode == expected, result.stdout + result.stderr
    assert "No GitHub remote" in result.stdout
    if expected:
        assert "fzf exited 2" in result.stderr


def test_alternate_route_to_same_github_destination_retains_publication(
    audit_env, tmp_path, remote_transport, monkeypatch
):
    import json

    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    url = remote_transport(path, "origin", "FAIL")
    ssh = "git@github.com:test/origin.git"
    git(path, "remote", "set-url", "--push", "origin", ssh)
    monkeypatch.setenv("AUDIT_TEST_REMOTES", json.dumps({url: "FAIL", ssh: str(remote)}))
    result = run_audit()
    assert result.returncode == 1  # retain the failed route diagnostic
    assert "test remote unavailable" in result.stdout
    assert "main: publication inconclusive" not in result.stdout
    assert "Local commits need review" not in result.stdout


def test_repository_transport_configuration_survives_isolation_without_second_rewrite(
    audit_env, tmp_path, remote_transport, stub_bin, monkeypatch
):
    import json
    import os

    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    url = remote_transport(path, "origin", remote)
    git(path, "config", "http.extraHeader", "Test: local configuration")
    monkeypatch.setenv("AUDIT_REQUIRE_HEADER", "Test: local configuration")
    # Rewrites are intentionally nonrecursive in Git. Applying them again to
    # an already effective URL would change the verification destination.
    global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    global_config.write_text(
        '[url "https://github.com/test/"]\n    insteadOf = alias:\n'
        '[url "https://github.com/wrong/"]\n    insteadOf = https://github.com/test/\n'
    )
    git(path, "remote", "set-url", "origin", "alias:origin.git")
    monkeypatch.setenv("AUDIT_TEST_REMOTES", json.dumps({url: str(remote)}))
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout


def test_live_stash_ref_is_reported_even_without_reflog(audit_env):
    _, root = audit_env
    path = repository(root / "project")
    (path / "file").write_text("saved")
    git(path, "stash", "push", "-qu", "-m", "save me")
    (path / ".git/logs/refs/stash").unlink()
    result = run_audit()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Stashes:" in result.stdout


def test_invalid_nested_worktree_link_is_unknown_without_inspecting_parent(audit_env):
    _, root = audit_env
    path = repository(root / "project")
    nested = path / "nested"
    git(path, "worktree", "add", "-q", "-b", "nested", str(nested))
    (nested / ".git").unlink()
    result = run_audit()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unknown:" in result.stdout
    assert "Worktrees: 1" in result.stdout
    assert "registered path is not this worktree" in result.stdout


def test_raw_branch_remote_includes_push_rewrite(audit_env, tmp_path, remote_transport):
    _, root = audit_env
    path = repository(root / "project")
    remote = tmp_path / "remote.git"
    git(path, "clone", "-q", "--bare", str(path), str(remote))
    remote_transport(path, "origin", remote)
    git(path, "remote", "remove", "origin")
    git(path, "config", "branch.main.remote", "https://example.com/origin.git")
    git(path, "config", "url.https://github.com/test/.pushInsteadOf", "https://example.com/")
    result = run_audit("--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No findings" in result.stdout and "No GitHub remote" not in result.stdout
