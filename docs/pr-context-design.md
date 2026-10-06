# Current-directory pull-request resolution

Design interview and accepted implementation contract for work-tracker item 275.
The user confirmed shared understanding under the invoked grill-with-docs workflow.

## Problem

The review checkout for CUBRID/cubrid PR 8095 uses local branch
`review-CBRD-27512-pr-8095`, while the fork branch is
`hornetmj:CBRD-27512-pgbuf-interrupt-policy`. Implicit `gh pr view` searches
using the local branch name and fails. Git's branch configuration already
records the fork URL and the actual fork branch.

## Accepted decisions

- A review checkout retains its PR association through branch renaming,
  upstream changes, local edits, and PR closure. Reassociation or clearing
  must be explicit. An explicit invocation selector overrides the association
  for that invocation only.
- Discovery selects the unique open PR. If none is open, it selects the unique
  historical PR. Multiple remaining candidates require explicit selection;
  show candidate URLs rather than guessing.
- Printing a recorded PR URL requires no network access. Discovery and live
  metadata queries use GitHub and preserve authentication/network errors.
- The association belongs to a local branch, not a directory. Renaming the
  branch preserves it; switching branches selects that branch's association
  or discovery.
- The resolver lives in the `my-git-utils` distribution. Chezmoi owns thin
  wrappers, including the previously unmanaged `gh-pr-view`, and the `ghpr`
  alias. Migrate `git-log-pr` alongside the CUBRID implicit-lookup consumers.
- The rebase helper uses shared lookup but retains its existing local-branch
  checks. Enabling rebases of renamed review branches is outside this change.
- Exclude the repository's default branch from upstream-based discovery, then
  try the local branch's published identity. Other ambiguous tracking
  arrangements require an explicit association.
- Detached HEAD requires an explicit PR selector; do not infer from the commit
  or directory name.
- Discovery is read-only. The review-worktree creator records associations;
  `gh-pr-associate URL` records one for an existing branch and
  `gh-pr-associate --clear` removes it.

## Implementation contract

All design questions are settled. The user confirmed shared understanding and
authorized implementation after the final contract summary.

### Ownership and interfaces

- Add a PR-context subpackage to `my-git-utils`, with `gh-pr-info` and
  `gh-pr-associate` entry points and a Python interface for `git-log-pr`.
- `gh-pr-info` accepts an optional selector, `--repo`, `--json` fields, and
  `--jq`. Requested live metadata is queried from GitHub. A request for only
  an associated URL is served locally. Keep output machine-readable and send
  errors to stderr.
- Chezmoi manages thin `gh-pr-url` and `gh-pr-view` wrappers, the background
  Starship caller, the rebase lookup, and the Nushell `ghpr` alias.
- Update `my-cubrid`'s `cubrid-pr-status`, `cubrid-pr-tc-base-check`,
  `cubrid-format-pr-diff.sh`, and `cubrid-pr-review-worktree`. The optional
  omitted-URL convenience in `cubrid-pr-latest-ci-run` is outside this fix.

### Resolution and errors

Resolve the enclosing Git worktree from the current directory. Prefer an
explicit selector, then the current branch's recorded PR association, then
upstream identity excluding the default branch, then local-branch identity.
Resolve named remotes and direct remote URLs; distinguish the fork repository
from the repository receiving the PR. CUBRID callers explicitly constrain the
receiving repository to `CUBRID/cubrid`.

Store a canonical URL in repository-local `branch.<name>.pr-url`. Git branch
renaming carries the branch configuration; switching branches does not reuse
the previous association. URL-only reads do not validate PR state online.
Live metadata may report local HEAD and PR head divergence without rejecting
the association.

Distinguish no match, ambiguous candidates, invalid context/configuration,
and GitHub/authentication/network errors. Do not treat operational errors as
permission to guess another PR. `git-log-pr` retains its ordinary no-PR graph
fallback, while operational lookup errors are reported as failures.

### Verification and delivery

Use temporary Git repositories and stub GitHub CLI responses for tests of
renamed fork branches, direct and named remotes, subdirectories, association
rename/switch/clear behavior, default-branch upstream exclusion, historical
and ambiguous PRs, detached HEAD, offline URL output, and operational errors.
Verify the original PR 8095 worktree against the task implementation without
installing it globally. Run repository-required tests/lint and exact-target
chezmoi diff checks. Commit meaningful source, docs, and verification changes
in clean task worktrees and present them for local merge review. Installation,
chezmoi deployment, and pushing remain separate explicitly requested actions.

## Inventory

Generic Git tooling is tracked in `my-git-utils`; its ADR 0001 owns reusable
commands in an editable Python distribution. Chezmoi tracks deployed personal
wrappers and aliases. `gh-pr-view` currently exists only as an unmanaged
deployed script. CUBRID-specific consumers are tracked in `my-cubrid`.

Additional implicit-lookup consumers include `git-log-pr` and the Nushell
`ghpr` alias. The rebase helper also requires a local branch named after the
GitHub branch; correcting lookup alone does not change that requirement.

## Verification results (2026-10-06)

- `my-git-utils`: `just test` passed all 50 tests; `just lint` passed.
- `my-cubrid`: review-worktree tests passed (22), PR-status tests passed (17),
  and testcase-base-check tests passed (6); formatter shell syntax passed.
- Chezmoi: wrapper tests passed (3), changed shell scripts passed syntax checks,
  and `nu-check` accepted the alias file. Exact-target rendered diffs for
  `gh-pr-url`, `gh-pr-view`, `git-rebase-pr.sh`, `starship-github-pr.sh`, and
  `alias.nu` contained only the intended changes.
- From `/home/vimkim/gh/cb/review-CBRD-27512-pr-8095`, the task wrapper resolved
  `https://github.com/CUBRID/cubrid/pull/8095`. The task version of
  `cubrid-pr-status --json --history 0` exited successfully with PR number
  8095 and its current GitHub head SHA. No association or source files in that
  CUBRID review worktree were changed.
- Global tools have not been installed, chezmoi targets have not been applied,
  and no branches have been pushed. Review-ready commits are the delivery
  boundary; local merges and installation/deployment follow their respective
  user authorizations.
