# my-git-utils

Personal git command-line utilities. Terms are defined in
[GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

| Command | Alias | What it shows |
|---|---|---|
| `git-log` | `gl` | compact colored `git log --graph`, labelling only refs worth reading |
| `git-log-pick` | `glp` | fzf-pick two commits from the `--all` map, then their log with `◀ A` / `◀ B` |
| `git-log-pr` | `glpr` | HEAD, the PR head and the PR base, marked `◀ HEAD` / `◀ PR-HEAD` / `◀ PR-BASE` |

Run any command with `-h` for its full usage.

## Install

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and
for the individual commands `fzf` (`git-log-pick`) and `gh` (`git-log-pr`).

```sh
git clone https://github.com/vimkim/my-git-utils.git ~/gh/my-git-utils
cd ~/gh/my-git-utils
just sync          # uv tool install --editable . --reinstall
```

The commands land in `~/.local/bin`, backed by one isolated environment.
Because the install is editable, code edits take effect immediately; re-run
`just sync` after dependencies change (`daily-update` does this after
fast-forwarding the checkout).

## git-log

Takes `git log` arguments as git does. No revision means `HEAD`; `-n 30`,
`--author X`, `--all`, `A..B` and `-- paths` all work.

```sh
gl                         # HEAD
gl --all                   # everything except hidden refs
gl develop HEAD -n 50      # two branches
gl --author=me -- src/     # pathspec after --
```

**Labels.** With named revisions, only those refs, HEAD, and the upstream of
each named branch are labelled. With `--all`, `--branches`, `--remotes` or
`--glob`, every ref except hidden refs is labelled. `--all-branch` labels every
ref except hidden refs regardless.

**Hidden refs.** `~/.config/my-git-utils/log.toml` (optional; override the path
with `MY_GIT_UTILS_LOG_CONFIG`):

```toml
hide    = ["^release"]       # regexes on the branch name without its remote
remotes = ["vk", "origin"]   # keep-list: refs of other remotes are hidden
```

Filters prune `--all`, `--branches`, `--remotes`, `--glob` and the
`git-log-pick` map, never a ref named on the command line. The remote keep-list
does nothing in a repository that has none of the listed remotes. Per run,
`--hide=REGEX` adds a pattern and `--no-hide` disables both filters.

**Marks.** `--mark=NAME=REV` appends `◀ NAME` to `REV`'s line.

## git-log-pick

```sh
glp            # pick A, then B (cursor starts on HEAD)
glp A          # pick B only
glp A B        # no picking
```

Other arguments go to `git-log`. In fzf, `ctrl-/` toggles the commit preview.

## git-log-pr

```sh
glpr                     # PR of the current branch
glpr 123 -n 80           # PR by number (or URL, or branch)
```

Prints the PR, its branches, and how HEAD relates to the PR head, then the log
of HEAD, the PR head, and the PR base. The PR head appears as the head
repository's remote-tracking branch when such a remote exists, else as
`<base-remote>/pr/<number>`. Refs are fetched only when missing or stale.
Without a PR, it shows HEAD, its upstream, and the default branch.

## Development

```sh
uv run pytest      # or: just test
just lint          # ruff check + format check
just fmt
```

Tests build throwaway repositories and stub `gh` and `fzf` on `PATH`.
