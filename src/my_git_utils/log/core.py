"""git-log (gl): compact, colored `git log --graph`.

Usage:
  git-log [git-log arguments] [--] [paths]

  Takes `git log` arguments as git does: no revision means HEAD; -n 30,
  --author X, --all, --branches, A..B and `-- paths` all work.

Labels (ref names next to commits):
  revisions named      label those refs, HEAD, and each named branch's
                       upstream (a raw commit gets the refs pointing at it)
  --all, --branches,   label every ref except hidden refs
  --remotes, --glob
  --all-branch         label every ref except hidden refs, whatever the revisions

Hidden refs (prune --all/--branches/--remotes/--glob, never a named ref):
  ~/.config/my-git-utils/log.toml
    hide    = ["^release"]       regexes on the branch name without its remote
    remotes = ["vk", "origin"]   keep-list; other remotes are hidden (no-op
                                 when the repository has none of them)
  --hide=REGEX         add a hide pattern for this run (repeatable)
  --no-hide            hide nothing this run

Marks:
  --mark=NAME=REV      append "◀ NAME" to REV's line (repeatable)
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field

from . import git
from .config import Filters, hidden_refs

PRETTY = (
    "%C(auto)%h %C(magenta)%as%C(reset) %C(blue)%an%C(reset)%C(auto)%d %s"
    " %C(black)%C(bold)%cr%C(reset)"
)
DEFAULT_OPTS = ["--graph", "--oneline", "--color", "--decorate", "--date-order"]
PAGER = "less -iRFSX"
MARK = "\x1b[1;33m"
RESET = "\x1b[m"

# git-log options that accept their value as the next argument (`-n 30`).
VALUE_OPTS = frozenset(
    """-n --max-count --skip --since --after --until --before --since-as-filter
    --author --committer --grep --grep-reflog --date --encoding --exclude --glob
    --diff-filter --decorate-refs --decorate-refs-exclude --stat-width
    --stat-name-width --stat-graph-width --word-diff-regex --output
    -S -G -L -O""".split()
)


def is_broad(arg: str) -> bool:
    """A revision option that selects many refs at once (filters apply)."""
    return arg in ("--all", "--branches", "--remotes") or arg.startswith(
        ("--branches=", "--remotes=", "--glob=")
    )


@dataclass
class Args:
    """git-log arguments split into ours and git's."""

    git_args: list[str] = field(default_factory=list)  # in order, before --
    paths: list[str] = field(default_factory=list)  # after --, without it
    dashdash: bool = False
    revs: list[str] = field(default_factory=list)  # positional revision tokens
    rev_at: list[int] = field(default_factory=list)  # indexes of revs in git_args
    marks: list[tuple[str, str]] = field(default_factory=list)
    hide: list[str] = field(default_factory=list)
    no_hide: bool = False
    label_all: bool = False

    @property
    def broad(self) -> bool:
        return any(is_broad(a) for a in self.git_args)

    def argv(self, revs: list[str] | None = None) -> list[str]:
        """Back to a command line, with `revs` replacing the positional revisions."""
        ours = [f"--mark={n}={r}" for n, r in self.marks]
        ours += [f"--hide={h}" for h in self.hide]
        ours += ["--no-hide"] * self.no_hide + ["--all-branch"] * self.label_all
        opts = [a for i, a in enumerate(self.git_args) if i not in self.rev_at]
        tail = ["--", *self.paths] if self.dashdash else []
        return [*ours, *opts, *(self.revs if revs is None else revs), *tail]


def parse(argv: list[str]) -> Args:
    args = Args()
    it = iter(argv)
    for arg in it:
        if arg == "--":
            args.dashdash = True
            args.paths = list(it)
        elif arg.startswith("--mark="):
            name, _, rev = arg[len("--mark=") :].partition("=")
            args.marks.append((name, rev))
        elif arg.startswith("--hide="):
            args.hide.append(arg[len("--hide=") :])
        elif arg == "--no-hide":
            args.no_hide = True
        elif arg == "--all-branch":
            args.label_all = True
        elif arg in VALUE_OPTS:
            args.git_args.append(arg)
            value = next(it, None)
            if value is not None:
                args.git_args.append(value)
        elif arg.startswith("-") and arg != "-":
            args.git_args.append(arg)
        else:
            args.rev_at.append(len(args.git_args))
            args.git_args.append(arg)
            args.revs.append(arg)
    return args


def named_refs(revs: list[str]) -> list[str]:
    """Full ref names to label for the named revisions (HEAD when none)."""
    refs: list[str] = []
    for rev in revs or ["HEAD"]:
        found = git.symbolic_full_names(rev)
        if not found:
            commit = git.commit_of(rev)
            if commit:
                found = git.out(
                    "for-each-ref", f"--points-at={commit}", "--format=%(refname)"
                ).split()
        for ref in found:
            if ref not in refs:
                refs.append(ref)
    for ref in list(refs):
        if ref.startswith("refs/heads/"):
            upstream = git.upstream_of(ref)
            if upstream and upstream not in refs:
                refs.append(upstream)
    return refs


def compress(hidden: set[str], refs: list[str]) -> list[str]:
    """Hidden refs as globs: a remote whose every ref is hidden becomes one glob."""
    by_remote: dict[str, list[str]] = {}
    for ref in refs:
        if ref.startswith("refs/remotes/"):
            by_remote.setdefault(ref.split("/", 3)[2], []).append(ref)
    patterns: list[str] = []
    covered: set[str] = set()
    for remote, remote_refs in sorted(by_remote.items()):
        if "/" in remote:
            continue
        if all(r in hidden for r in remote_refs):
            patterns.append(f"refs/remotes/{remote}/*")
            covered.update(remote_refs)
    patterns += sorted(hidden - covered)
    return patterns


def exclude_for(option: str, patterns: list[str]) -> list[str]:
    """--exclude args in the form `option` expects (git strips refs/heads/ etc.)."""
    if option.startswith("--branches"):
        prefix = "refs/heads/"
    elif option.startswith("--remotes"):
        prefix = "refs/remotes/"
    else:
        prefix = ""
    return [f"--exclude={p[len(prefix) :]}" for p in patterns if p.startswith(prefix)]


def command(args: Args, filters: Filters | None = None) -> list[str]:
    """The `git log` command line for parsed arguments."""
    filters = filters or Filters.load()
    if args.no_hide:
        filters = Filters()
    else:
        filters = Filters(hide=filters.hide + args.hide, remotes=filters.remotes)

    named = named_refs(args.revs)
    git_args = list(args.git_args)
    deco: list[str] = []
    if args.broad or args.label_all:
        hidden = hidden_refs(filters, keep=set(named))
        # Named refs are never in `hidden`, so no glob below can swallow one.
        patterns = compress(hidden, git.all_refs()) if hidden else []
        rebuilt: list[str] = []
        for arg in git_args:
            if is_broad(arg):
                rebuilt += exclude_for(arg, patterns)
            rebuilt.append(arg)
        git_args = rebuilt
        deco = [f"--decorate-refs-exclude={p}" for p in patterns]
    else:
        # HEAD keeps the filter non-empty: no --decorate-refs labels everything.
        deco = [f"--decorate-refs={r}" for r in ["HEAD", *named]]

    cmd = ["git", "log", *DEFAULT_OPTS, *deco, f"--pretty=format:{PRETTY}", *git_args]
    if args.dashdash:
        cmd += ["--", *args.paths]
    return cmd


def resolve_marks(marks: list[tuple[str, str]]) -> dict[str, list[str]]:
    resolved: dict[str, list[str]] = {}
    for name, rev in marks:
        commit = git.commit_of(rev)
        if commit:
            resolved.setdefault(commit, []).append(name)
    return resolved


def marked(line: str, marks: dict[str, list[str]]) -> str:
    short = git.first_hash(line)
    if not short:
        return line
    for commit, names in marks.items():
        if commit.startswith(short):
            end = "\n" if line.endswith("\n") else ""
            return f"{line.rstrip(chr(10))} {MARK}◀ {' '.join(names)}{RESET}{end}"
    return line


def run_marked(cmd: list[str], marks: dict[str, list[str]]) -> int:
    """Stream git log through the marker into less (or stdout when piped)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, errors="replace")
    pager = None
    out = sys.stdout
    if sys.stdout.isatty():
        pager = subprocess.Popen(PAGER.split(), stdin=subprocess.PIPE, text=True, errors="replace")
        out = pager.stdin
    try:
        for line in proc.stdout:
            out.write(marked(line, marks))
        if pager:
            pager.stdin.close()
    except BrokenPipeError:  # pager quit early
        proc.terminate()
    if pager:
        pager.wait()
    else:
        out.flush()
    return proc.wait()


def run(argv: list[str]) -> int:
    """Show the log for `argv`; return git's exit status."""
    args = parse(argv)
    cmd = command(args)
    marks = resolve_marks(args.marks)
    if not marks:
        os.execvpe("git", cmd, {**os.environ, "GIT_PAGER": PAGER})
    return run_marked(cmd, marks)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if not git.in_repo():
        print("git-log: not a git repository", file=sys.stderr)
        return 128
    return run(argv)
