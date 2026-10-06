from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import git

from my_git_utils.pr import context

URL = "https://github.com/example/origin/pull/8095"


def row(number=8095, owner="example", name="vk", branch="feature", state="open"):
    return {
        "number": number,
        "html_url": f"https://github.com/example/origin/pull/{number}",
        "state": state,
        "head": {"ref": branch, "repo": {"full_name": f"{owner}/{name}"}},
    }


@pytest.fixture
def github(repo, stub_bin, tmp_path, monkeypatch):
    fixture = tmp_path / "github.json"
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PR_FIXTURE", str(fixture))
    monkeypatch.setenv("PR_CALLS", str(calls))
    stub = stub_bin / "gh"
    stub.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["PR_CALLS"], "a") as f: f.write(json.dumps(args)+"\\n")
with open(os.environ["PR_FIXTURE"]) as f: data = json.load(f)
if "error" in data:
 print(data["error"], file=sys.stderr); sys.exit(1)
if args[:2] == ["repo", "view"]:
 value = {"nameWithOwner": "example/origin", "defaultBranchRef": {"name": "main"}}
elif args[:1] == ["api"]:
 params = dict(x.split("=", 1) for x in args if "=" in x)
 state = "open" if "states: [OPEN]" in params["query"] else "closed"
 ref = params["ref"]
 pages = []
 for key, values in data.get("pulls", {}).items():
  selector, found_state = key.rsplit("/", 1)
  if found_state == state and (selector == "" or selector.split(":",1)[-1] == ref):
   pages.extend(values)
 value = [{"data": {"repository": {"pullRequests": {"nodes": [
   {"url": x["html_url"], "headRefName": x["head"]["ref"],
    "headRepository": {"nameWithOwner": x["head"]["repo"]["full_name"]},
    "headRepositoryOwner": {"login": x["head"]["repo"]["full_name"].split("/")[0]}}
   for x in page]}}}} for page in pages]
elif args[:2] == ["pr", "view"]:
 value = data.get("pr", {"url": "https://github.com/example/origin/pull/8095",
                         "number": 8095, "state": "OPEN"})
else:
 print("unexpected gh call", file=sys.stderr); sys.exit(1)
print(json.dumps(value))
""")
    stub.chmod(0o755)

    def configure(pulls=None, **extra):
        fixture.write_text(json.dumps({"pulls": pulls or {}, **extra}))

    configure({"example:feature/open": [[row()]]})
    return configure, calls


def test_renamed_fork_branch_and_direct_remote(repo, github):
    path = Path(repo["path"])
    git(path, "branch", "-m", "review-CBRD-27512-pr-8095")
    git(
        path,
        "config",
        "branch.review-CBRD-27512-pr-8095.remote",
        "https://github.com/example/vk.git",
    )
    assert context.resolve_url() == URL
    assert git(path, "config", "--get", "branch.review-CBRD-27512-pr-8095.remote")
    assert "pr-url" not in git(path, "config", "--local", "--list")


def test_named_remote_and_subdirectory(repo, github, monkeypatch):
    sub = Path(repo["path"]) / "src" / "storage"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert context.resolve_url() == URL


def test_association_offline_rename_switch_clear(repo, github, capsys):
    path = Path(repo["path"])
    configure, calls = github
    assert context.associate_main([URL]) == 0
    git(path, "branch", "-m", "renamed")
    calls.unlink()
    configure(error="authentication failed")
    assert context.info_main(["--json", "url", "--jq", ".url"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == URL
    assert not calls.exists()
    git(path, "switch", "-q", "main")
    with pytest.raises(context.LookupError):
        context.resolve_url()
    git(path, "switch", "-q", "renamed")
    assert context.associate_main(["--clear"]) == 0
    with pytest.raises(context.LookupError):
        context.resolve_url()


def test_live_fields_query_even_with_association(repo, github):
    path = Path(repo["path"])
    git(path, "config", "--local", "branch.feature.pr-url", URL)
    configure, _ = github
    configure(error="network unreachable")
    with pytest.raises(context.LookupError, match="network unreachable"):
        context.read_pr(fields="url,state")


def test_unique_open_beats_history(repo, github):
    configure, _ = github
    configure(
        {
            "example:feature/open": [[row()]],
            "example:feature/closed": [[row(1, state="closed"), row(2, state="closed")]],
        }
    )
    assert context.resolve_url() == URL


def test_unique_historical(repo, github):
    configure, _ = github
    configure({"example:feature/closed": [[row(state="closed")]]})
    assert context.resolve_url() == URL


@pytest.mark.parametrize("state", ["open", "closed"])
def test_ambiguity_across_pages(repo, github, state):
    configure, _ = github
    configure({f"example:feature/{state}": [[row(1, state=state)], [row(2, state=state)]]})
    with pytest.raises(context.AmbiguousPR, match="pull/1.*\n.*pull/2"):
        context.resolve_url()


def test_wrong_fork_repository_is_excluded(repo, github):
    configure, _ = github
    configure({"example:feature/open": [[row(name="other")]]})
    with pytest.raises(context.NoPR):
        context.resolve_url()


def test_default_upstream_is_not_selected(repo, github):
    path = Path(repo["path"])
    git(path, "config", "branch.feature.remote", "origin")
    git(path, "config", "branch.feature.merge", "refs/heads/main")
    configure, calls = github
    configure({"example:main/open": [[row(branch="main", name="origin")]], "/open": [[row()]]})
    assert context.resolve_url() == URL
    assert "ref=main" not in calls.read_text()


def test_local_branch_fallback(repo, github):
    path = Path(repo["path"])
    git(path, "config", "--unset", "branch.feature.remote")
    git(path, "config", "--unset", "branch.feature.merge")
    configure, _ = github
    configure({"/open": [[row()]]})
    assert context.resolve_url() == URL


def test_no_match_is_distinct_from_operational_error(repo, github):
    configure, _ = github
    configure()
    with pytest.raises(context.NoPR):
        context.resolve_url()
    configure(error="HTTP 401: Bad credentials")
    with pytest.raises(context.LookupError, match="Bad credentials") as exc:
        context.resolve_url()
    assert not isinstance(exc.value, context.NoPR)


def test_detached_requires_selector(repo, github):
    git(Path(repo["path"]), "checkout", "-q", "--detach")
    with pytest.raises(context.ContextError, match="detached HEAD"):
        context.resolve_url()
    assert context.resolve_url(URL) == URL


def test_explicit_selector_overrides_without_rewriting(repo, github):
    path = Path(repo["path"])
    git(path, "config", "--local", "branch.feature.pr-url", URL)
    other = "https://github.com/example/origin/pull/123"
    assert context.resolve_url(other) == other
    assert git(path, "config", "--get", "branch.feature.pr-url") == URL


def test_recorded_repository_mismatch(repo, github):
    git(Path(repo["path"]), "config", "--local", "branch.feature.pr-url", URL)
    with pytest.raises(context.ContextError, match="repository"):
        context.resolve_url(repo="other/project")


def test_invalid_association_does_not_fall_back(repo, github):
    git(Path(repo["path"]), "config", "--local", "branch.feature.pr-url", "not-a-url")
    with pytest.raises(context.ContextError):
        context.resolve_url()


def test_failed_association_validation_preserves_previous(repo, github):
    path = Path(repo["path"])
    git(path, "config", "--local", "branch.feature.pr-url", URL)
    configure, _ = github
    configure(error="HTTP 404: Not Found")
    assert context.associate_main(["https://github.com/example/origin/pull/42"]) != 0
    assert git(path, "config", "--get", "branch.feature.pr-url") == URL


def test_outside_repository_requires_explicit_selector(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(context.ContextError, match="Git worktree"):
        context.resolve_url()
    assert context.resolve_url(URL) == URL


def test_explicit_owner_selector_allows_renamed_fork(repo, github):
    configure, _ = github
    configure({"example:feature/open": [[row(name="renamed-fork")]]})
    assert context.resolve_url("example:feature") == URL


def test_numeric_selector_and_invalid_metadata(repo, github):
    configure, _ = github
    assert context.resolve_url("8095", repo="example/origin") == URL
    configure(pr={"number": 8095})
    with pytest.raises(context.LookupError, match="invalid PR metadata"):
        context.resolve_url("8095")


def test_graphql_errors_do_not_become_no_match(repo, monkeypatch):
    monkeypatch.setattr(context, "gh_json", lambda *args: [{"data": None, "errors": []}])
    with pytest.raises(context.LookupError, match="invalid pull-request metadata"):
        context.candidates("example/origin", "feature", None, "open")


def test_cli_entry_point_uses_association_without_github(repo, github):
    import subprocess
    import sys

    git(Path(repo["path"]), "config", "--local", "branch.feature.pr-url", URL)
    result = subprocess.run(
        [str(Path(sys.executable).parent / "gh-pr-info"), "--json", "url", "--jq", ".url"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == URL
    _, calls = github
    assert not calls.exists()


def test_named_remote_with_slash(repo, github):
    path = Path(repo["path"])
    git(path, "remote", "rename", "vk", "review/fork")
    assert context.resolve_url() == URL
