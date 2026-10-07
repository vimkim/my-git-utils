# my-git-utils

Personal git command-line utilities. Terms are defined in
[GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

| Command | Alias | What it shows |
|---|---|---|
| `git-log` | `gl` | compact colored `git log --graph`, labelling only refs worth reading |
| `git-log-pick` | `glp` | fzf-pick two commits from the `--all` map, then their log with `◀ A` / `◀ B` |
| `git-log-pr` | `glpr` | HEAD, the PR head and the PR base, marked `◀ HEAD` / `◀ PR-HEAD` / `◀ PR-BASE` |
| `git-unsynced` | — | local work needing attention for preservation on GitHub |
| `gh-pr-info` | — | the associated or discovered PR, as JSON |
| `gh-pr-associate` | — | explicitly record or clear the current branch's PR association |

Run any command with `-h` for its full usage.

## Install

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and
for the individual commands `fzf` (`git-log-pick`) and `gh` (live PR lookup).
`gh-pr-info --jq` also requires `jq`; `git-unsynced --choose` requires fzf and lazygit.

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

## git-unsynced

```sh
git-unsynced                       # fresh report of findings and unknown checks
git-unsynced --all                 # also show repositories with no findings
git-unsynced --choose              # review worktrees in lazygit, repeating after each visit
git-unsynced --offline             # use cached remote histories without contacting GitHub
git-unsynced --root ~/projects     # add a scan root; repeat for several roots
git-unsynced --config audit.toml   # use a chosen personal configuration
```

Discovers projects from lazygit history and `~/gh`, `~/temp`, and `~/tmp`, then
includes every registered worktree. Repositories sharing a Git common directory
are grouped. Hidden project directories are included; dependency trees, Git
metadata, ignored files, and reflog-only revisions are outside audit coverage.
Directory symlinks are followed only when explicitly supplied or registered.

The report checks every branch, detached worktree commits, worktree files,
shared stashes, and tags. Publication on any configured GitHub destination
counts, including forks, separate push URLs, and explicit branch remote URLs.
Commit identity and ancestry are compared, so work published through equivalent
changes after a squash merge, rebase, or cherry-pick can still need review.
Being behind a remote branch alone produces no finding.

Fresh remote checks use disposable Git directories and preserve local refs,
working files, the index, and `FETCH_HEAD`. Failures remain visible; another
successful remote can still prove publication. Shallow history and missing
objects make absence checks inconclusive. Tags require the same name and direct
object identity, including the annotation object. Offline evidence is labelled
cached; ordinary local tags do not prove remote publication.

The chooser lists worktrees directly and opens the exact selected path with
`lazygit -p`. Unchecked branches, stashes, and tags select the primary existing
worktree. After lazygit exits, the repository is refreshed and the chooser
returns with updated rows. Esc, no matches, or an empty list finish the session.
Publication remains a user action in lazygit.

Personal settings live in `~/.config/my-git-utils/audit.toml` (respecting
`XDG_CONFIG_HOME`), separately from Git log display filters:

```toml
roots = ["~/gh", "~/temp", "~/tmp"] # replaces the defaults; --root adds paths
exclude = ["~/gh/intentionally-local"] # excludes the entire project and its worktrees
timeout = 30                       # seconds per remote check
concurrency = 4                    # maximum repositories checked at once
```

All settings are optional. Lazygit history uses
`$XDG_STATE_HOME/lazygit/state.yml` (default `~/.local/state/lazygit/state.yml`),
falling back to `$XDG_CONFIG_HOME/lazygit/state.yml` when absent. Malformed
history, failed checks, and missing registered paths appear in the report and
coverage totals. Colors follow terminal detection and `NO_COLOR`.

Exit codes: `0` completed, including ordinary review findings; `1` incomplete
operational checks or chooser failure; `2` invalid options or configuration.
No-finding results are scoped to the displayed coverage and evidence freshness.
See the [accepted design](docs/git-unsynced-design.md) for verification policy.

## Development

```sh
uv run pytest      # or: just test
just lint          # ruff check + format check
just fmt
```

Tests build throwaway repositories and stub Git transports, `gh`, `fzf`, and
`lazygit` on `PATH`.
