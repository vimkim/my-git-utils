# my-git-utils

Personal git command-line utilities. Terms are defined in
[GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

| Command | Alias | What it shows |
|---|---|---|
| `git-log` | `gl` | compact colored `git log --graph`, labelling only refs worth reading |
| `git-log-pick` | `glp` | fzf-pick two commits from the `--all` map, then their log with `◀ A` / `◀ B` |
| `git-log-pr` | `glpr` | HEAD, the PR head and the PR base, marked `◀ HEAD` / `◀ PR-HEAD` / `◀ PR-BASE` |
| `gh-pr-info` | — | the associated or discovered PR, as JSON |
| `gh-pr-associate` | — | explicitly record or clear the current branch's PR association |

Run any command with `-h` for its full usage.

## Install

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and
for the individual commands `fzf` (`git-log-pick`) and `gh` (live PR lookup).
`gh-pr-info --jq` also requires `jq`.

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
Authentication, network, ambiguous-selection, and invalid-context errors are
reported as failures rather than producing a no-PR fallback graph.

## PR context

```sh
gh-pr-info                                      # live PR metadata as JSON
gh-pr-info --json url --jq .url                 # current branch's PR URL
gh-pr-info 8095 --repo CUBRID/cubrid --json url
gh-pr-associate https://github.com/CUBRID/cubrid/pull/8095
gh-pr-associate --clear
```

Resolution prefers an explicit selector, the current branch's recorded PR
association, its GitHub tracking identity, then its local branch's published
identity. It works inside worktree subdirectories and with fork remote URLs
or named remotes. Tracking the receiving repository's default branch does not
associate a feature branch with a PR for that default branch.

Discovery is read-only. It selects a unique open PR, then a unique closed or
merged PR, and reports candidate URLs if multiple matches remain. It uses
paginated GitHub queries filtered by branch name, with fork identity checked
when known. Detached HEAD requires an explicit selector; neither commit IDs nor
directory names are used to guess a PR.

`gh-pr-associate` validates the supplied URL online before recording it in
repository-local `branch.<name>.pr-url`. Renaming the branch preserves this
association; switching branches changes which association is read. Clear it
before repurposing a branch. Recorded URL-only lookup works without `gh` or a
network connection. Other requested fields are live GitHub metadata; local
edits and an older review snapshot do not invalidate the association.

Exit codes: `0` success, `1` no matching PR, `2` invalid context or ambiguous
selection, `3` an operational Git/GitHub/tool failure. `--jq` uses `jq -r`;
without it, stdout contains one JSON object and diagnostics go to stderr.

The personal `gh-pr-url` wrapper lives in chezmoi and uses
`gh-pr-info --json url --jq .url`. Install the new entry points from the main
checkout with `just sync` after merging; deploy each reviewed chezmoi target
separately. CUBRID callers use the same resolver with `--repo CUBRID/cubrid`.

## Development

```sh
uv run pytest      # or: just test
just lint          # ruff check + format check
just fmt
```

Tests build throwaway repositories and stub `gh` and `fzf` on `PATH`.
