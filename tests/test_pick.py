from __future__ import annotations

import re

from my_git_utils.log import pick

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_two_revisions_skip_the_picker(repo, capsys):
    assert pick.main(["-n", "5", "main", "feature", "--"]) == 0
    out = ANSI.sub("", capsys.readouterr().out)
    assert re.search(r"base .*◀ A", out)
    assert re.search(r"feat .*◀ B", out)


def test_picker_map_is_filtered_all(repo, isolated_env, stub_bin, capsys):
    isolated_env.write_text('hide = ["^release"]\nremotes = ["vk", "origin"]\n')
    # A fake fzf that picks the first line containing a commit.
    fzf = stub_bin / "fzf"
    fzf.write_text("#!/bin/sh\ngrep -m1 '[0-9a-f]\\{7\\}'\n")
    fzf.chmod(0o755)
    lines = ANSI.sub("", pick.graph(pick.core.parse([])).decode())
    assert "feat" in lines and "rel" not in lines and "other" not in lines
    assert pick.main(["main"]) == 0
    assert "◀ A" in ANSI.sub("", capsys.readouterr().out)


def test_head_position(repo):
    lines = pick.graph(pick.core.parse([]))
    pos = pick.head_position(lines)
    assert "feat" in lines.decode().splitlines()[pos - 1]
