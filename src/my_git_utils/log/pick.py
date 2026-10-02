"""git-log-pick (glp): pick two commits from the `--all` map with fzf, then show
`git-log <A> <B>` with the picks marked "◀ A" / "◀ B".

Each pick is a point in history, not a branch name: the final log shows only
what is reachable backward from A and from B. Type a branch name in fzf to
jump to its tip, or move the cursor to any older commit to start from there.

Usage:
  glp                  # pick A, then pick B
  glp A                # A given, pick B
  glp A B              # no picking, straight to the log
  glp -n30 --since=1.month
                       # other arguments go to git-log
  glp --all-branch     # label every ref, not just those at A and B
  glp --hide=REGEX     # hide more refs from the map (see git-log -h)
  glp --no-hide        # hide nothing from the map

In the picker: the cursor starts on HEAD, so Enter alone picks HEAD.
Enter confirms, Esc aborts, ctrl-/ toggles the commit preview.
Lines with only graph edges (no commit) are not selectable; the picker reopens.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from . import core, git
from .config import Filters

# fzf runs the preview through $SHELL; pin it to sh so nushell/fish never parse
# it, and keep it a plain command: fzf expands regex braces like {7,40}.
PREVIEW = f"{shlex.quote(sys.executable)} -m my_git_utils.log.pick --preview-line {{}}"


def graph(args: core.Args) -> bytes:
    """The filtered `--all` map, as git-log would draw it, without paging."""
    map_args = core.Args(git_args=["--all"], hide=args.hide, no_hide=args.no_hide, label_all=True)
    cmd = core.command(map_args, Filters.load())
    cmd = [a for a in cmd if not a.startswith("--pretty=")]
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout


def head_position(lines: bytes) -> int | None:
    """1-based index of the graph line for HEAD, or None (e.g. unborn HEAD)."""
    head = git.commit_of("HEAD")
    if not head:
        return None
    for i, line in enumerate(lines.decode(errors="replace").splitlines(), 1):
        short = git.first_hash(line)
        if short and head.startswith(short):
            return i
    return None


def pick(prompt: str, header: str, lines: bytes) -> str | None:
    """The selected commit hash, or None if the user aborted."""
    pos = head_position(lines)
    while True:
        proc = subprocess.run(
            [
                "fzf",
                "--ansi",
                "--no-sort",
                "--reverse",
                "--height=80%",
                f"--prompt={prompt} > ",
                f"--header={header}",
                f"--preview={PREVIEW}",
                "--preview-window=right,50%,wrap",
                "--bind=ctrl-/:toggle-preview",
                *([f"--bind=load:pos({pos})"] if pos else []),
            ],
            input=lines,
            stdout=subprocess.PIPE,
            env={**os.environ, "SHELL": "/bin/sh"},
        )
        if proc.returncode != 0:  # Esc / ctrl-c / no match
            return None
        short = git.first_hash(proc.stdout.decode(errors="replace"))
        if short:
            return short


def preview(line: str) -> int:
    short = git.first_hash(line)
    if not short:
        return 0  # graph-only line: empty preview
    return subprocess.run(["git", "show", "--color=always", "--stat", "-p", short]).returncode


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--preview-line"]:
        return preview(" ".join(argv[1:]))
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if not git.in_repo():
        print("git-log-pick: not a git repository", file=sys.stderr)
        return 128

    args = core.parse(argv)
    revs = list(args.revs)
    if len(revs) > 2:
        print("git-log-pick: at most two revisions", file=sys.stderr)
        return 2

    if len(revs) < 2:
        if not shutil.which("fzf"):
            print("git-log-pick: fzf is required to pick commits", file=sys.stderr)
            return 127
        lines = graph(args)
        if not revs:
            a = pick("A", "pick the first starting point   [ctrl-/ preview]", lines)
            if a is None:
                return 130
            revs.append(a)
        b = pick("B", f"A = {revs[0]} — pick the second starting point   [ctrl-/ preview]", lines)
        if b is None:
            return 130
        revs.append(b)

    args.marks += [("A", revs[0]), ("B", revs[1])]
    return core.run(args.argv(revs))


if __name__ == "__main__":
    sys.exit(main())
