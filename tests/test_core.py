from __future__ import annotations

import re
import subprocess

from my_git_utils.log import core
from my_git_utils.log.config import Filters

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def show(argv: list[str], filters: Filters | None = None) -> str:
    """What git-log prints for `argv`, without colors."""
    cmd = core.command(core.parse(argv), filters or Filters())
    out = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True).stdout
    return ANSI.sub("", out)


def subjects(output: str) -> set[str]:
    return set(re.findall(r"\b(base|rel|other|feat)\b", output))


# --- argument parsing -------------------------------------------------------


def test_parse_separates_values_paths_and_own_flags():
    args = core.parse(
        ["-n", "30", "--author", "me", "--mark=A=HEAD", "--hide=^x", "main", "--", "src"]
    )
    assert args.git_args == ["-n", "30", "--author", "me", "main"]
    assert args.revs == ["main"]
    assert args.paths == ["src"]
    assert args.marks == [("A", "HEAD")]
    assert args.hide == ["^x"]


def test_value_equal_to_a_rev_is_not_a_rev():
    args = core.parse(["--grep", "main", "main"])
    assert args.revs == ["main"]
    assert args.argv(["dev"]) == ["--grep", "main", "dev"]


def test_argv_keeps_revs_before_dashdash():
    args = core.parse(["-n5", "--no-hide", "--", "a.txt"])
    assert args.argv(["x", "y"]) == ["--no-hide", "-n5", "x", "y", "--", "a.txt"]


# --- revisions and labels ---------------------------------------------------


def test_no_revision_means_head(repo):
    assert subjects(show([])) == {"base", "feat"}


def test_default_labels_head_branch_and_its_upstream(repo):
    out = show([])
    assert "HEAD -> feature" in out
    assert "vk/feature" in out
    assert "origin/main" not in out


def test_all_shows_everything_without_filters(repo):
    assert subjects(show(["--all"])) == {"base", "rel", "other", "feat"}


def test_dash_n_with_separate_value(repo):
    assert subjects(show(["-n", "1"])) == {"feat"}


def test_paths_after_dashdash(repo):
    assert show(["--", "no-such-file"]) == ""


# --- hidden refs ------------------------------------------------------------


def test_hide_regex_matches_branch_name_without_remote(repo):
    hidden = Filters(hide=["^release"]).hidden_refs(
        ["refs/heads/release/1.0", "refs/remotes/vk/release/1.0", "refs/heads/feature"],
        ["vk"],
    )
    assert hidden == {"refs/heads/release/1.0", "refs/remotes/vk/release/1.0"}


def test_remote_keep_list_hides_other_remotes(repo):
    hidden = Filters(remotes=["vk"]).hidden_refs(
        ["refs/remotes/vk/a", "refs/remotes/other/b", "refs/heads/c"], ["vk", "other"]
    )
    assert hidden == {"refs/remotes/other/b"}


def test_keep_list_is_ignored_when_repo_has_none_of_those_remotes(repo):
    hidden = Filters(remotes=["vk"]).hidden_refs(["refs/remotes/other/b"], ["other"])
    assert hidden == set()


def test_filters_prune_all(repo):
    filters = Filters(hide=["^release"], remotes=["vk", "origin"])
    out = show(["--all"], filters)
    assert subjects(out) == {"base", "feat"}
    assert "other/topic" not in out and "release" not in out


def test_filters_prune_branches_and_remotes_forms(repo):
    filters = Filters(hide=["^release"], remotes=["vk", "origin"])
    assert subjects(show(["--branches"], filters)) == {"base", "feat"}
    assert subjects(show(["--remotes"], filters)) == {"base", "feat"}


def test_named_ref_is_never_hidden(repo):
    filters = Filters(hide=["^release"], remotes=["vk", "origin"])
    out = show(["--all", "other/topic", "release/1.0"], filters)
    assert subjects(out) == {"base", "rel", "other", "feat"}
    assert "other/topic" in out and "release/1.0" in out


def test_cli_hide_adds_and_no_hide_bypasses(repo, isolated_env):
    isolated_env.write_text('remotes = ["vk", "origin"]\n')
    assert subjects(show(["--all", "--hide=^release"], Filters.load())) == {"base", "feat"}
    cmd = core.command(core.parse(["--all", "--no-hide"]), Filters.load())
    assert not any(a.startswith("--exclude") for a in cmd)


def test_config_file_is_optional(isolated_env):
    assert Filters.load() == Filters()


# --- marks ------------------------------------------------------------------


def test_marks_annotate_lines(repo, capsys):
    assert core.run(["--mark=A=main", "--mark=B=feature", "main", "feature"]) == 0
    out = ANSI.sub("", capsys.readouterr().out)
    assert re.search(r"feat .*◀ B", out)
    assert re.search(r"base .*◀ A", out)
