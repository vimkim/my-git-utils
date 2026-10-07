# Local Git work audit design

Status: proposed for review on 2026-10-07. All three interview rounds are
settled; confirmation of shared understanding is pending. The implementation
host is `my-git-utils`. This document specifies planned behavior.

## Settled requirements

- The goal is a local work audit: identify local work still needing attention
  for preservation on GitHub.
- Cover unpublished commits on every local branch, uncommitted files,
  untracked files, stashes, detached worktree commits, and unpublished tags.
  Ignored files and abandoned reflog-only revisions are outside coverage.
  Being behind a remote branch is informational rather than sufficient
  evidence of local work needing publication.
- Discover repositories from lazygit visit history and selected project
  folders: `~/gh`, `~/temp`, and `~/tmp`. Include discovered repositories'
  registered worktrees even when those paths are outside the scan roots.
  Group worktrees sharing repository history while inspecting each worktree's
  unfinished files.
- Verified publication means presence on any configured GitHub remote, rather
  than requiring origin or the branch's intended push destination. GitHub
  remotes may include personal forks, organization repositories, and named
  review remotes. Explicit branch remote/push-remote URLs also count as
  configured destinations.
- Contact configured GitHub remotes by default before comparing histories.
  Provide an offline mode. A failed remote refresh produces unknown status
  for publication claims not established by another successful remote check.
- Compare commit identities and ancestry. Original commits absent from remote
  history remain review findings even when their changes may have been
  squash-merged, rebased, or cherry-picked. The first version does not infer
  equivalent changes or query PR metadata to suppress these findings.
- The default command displays a colored terminal report.
- Show repositories with findings or unknown state by default, plus totals
  for all scanned repositories and worktrees. `--all` also shows repositories
  with no findings.
- Repositories without a configured GitHub remote appear as "No GitHub
  remote." Provide configurable audit exclusions for projects intentionally
  kept local; do not infer exclusions from their lack of remotes.
- The explicit `--choose` option adds an fzf picker that opens the selected
  worktree in lazygit. List worktrees directly with repository name, branch,
  path, and findings rather than requiring a second worktree-selection step.
  Branch findings without a checked-out worktree point to the repository's
  primary worktree for review in lazygit. After lazygit exits, refresh the
  selected repository and return to the picker so several repositories can be
  reviewed in one session.
- Publication remains a user action through lazygit.
- Implement the command in the existing standalone `my-git-utils` Python
  distribution. Chezmoi continues to own personal configuration and bootstrap.

## Evidence

- Installed lazygit version: 0.65.1. Its CLI help exposes `--path` for opening
  a repository and has no recent-repository export option.
- `/home/vimkim/.local/state/lazygit/state.yml` contains 81 `recentrepos`
  entries, all existing paths when inspected on 2026-10-07. Several entries
  are worktrees of the same repository.
- Read-only inspection grouped those paths into 44 distinct repositories.
  Their registered worktrees include 197 existing paths and seven missing
  registrations. Of the existing paths, 117 are absent from lazygit history,
  including the initial chezmoi design worktree. A discovered repository's
  registered worktrees are therefore a necessary source of audit coverage.
- History has 62 paths under `~/gh`, 14 under `~/temp`, and five outliers:
  `~/.local/share/chezmoi`, `~/.config/nvim`, `~/my-cubrid`,
  `~/tmp/seminar-helper`, and `/home/dev/cubrid-dev2-server`.
- Eleven discovered repositories have no remotes. The report needs to retain
  this distinction from failed remote refreshes and verified remote state.
- Lazygit persists `RecentRepos` in its application state and records visits
  from the working directory. Its recent-repository list is not an inventory
  of all repositories on the machine. Primary sources:
  [application state](https://github.com/jesseduffield/lazygit/blob/v0.65.1/pkg/config/app_config.go#L845-L849)
  and [visit recording](https://github.com/jesseduffield/lazygit/blob/v0.65.1/pkg/gui/recent_repos_panel.go).
- `/home/vimkim/my-cubrid/CUBRID.md` states that CUBRID `origin` is the
  organization remote and `vk` is the personal fork. Ordinary personal
  branches use `vk`; `feature/*` branches use `origin`. Verified publication
  can be established by either GitHub remote under the chosen policy.
- `fzf` and `work-tracker` are installed. System Python has no PyYAML package;
  parsing lazygit's state will need a suitable dependency or adapter.
- The existing `/home/vimkim/gh/my-git-utils` package already contains colored
  Git graph commands, an fzf picker, and PR context commands, but no repository
  audit command. Its `docs/adr/0001-standalone-repo-uv-tool-install.md` places
  growing Git utility implementation in that standalone repository, with
  chezmoi owning personal configuration and bootstrap. Chezmoi already has
  `.chezmoiscripts/run_once_after_install-my-git-utils.sh`. The chosen host
  follows that established arrangement.
- The installed my-git-utils tool environment has Rich and `tomllib`, but no
  PyYAML. Installed fzf is 0.74.4. Python, Git, and uv are available.

## Command and presentation

The proposed command name is `git-unsynced`. The following option names and
presentation details are routine, reversible defaults presented for review.

| Command | Planned behavior |
| --- | --- |
| `git-unsynced` | Fresh audit; colored report of findings and unknown states, with coverage totals |
| `git-unsynced --all` | Fresh audit; include repositories with no findings |
| `git-unsynced --choose` | Report, then choose a worktree and review it in lazygit; repeat until cancelled |
| `git-unsynced --offline` | Use locally available remote information, explicitly marked cached or inconclusive |
| `git-unsynced --root PATH` | Add a project scan root; repeat the option for several roots |
| `git-unsynced --config PATH` | Read a chosen personal audit configuration |

These options can be combined. A normal report requires Git and the installed
Python utility, while `--choose` additionally requires fzf and lazygit. Missing
interactive tools should be reported when the chooser is requested.

Group findings by repository, show affected branches and worktree paths, and
keep repository-wide stashes and tags distinct from individual worktree files.
Use color together with readable labels; plain output remains understandable
when redirected, and color follows terminal detection and `NO_COLOR`.

| Finding | Meaning |
| --- | --- |
| Local commits need review | Commit identities are absent from all successfully verified GitHub histories, with no remaining inconclusive remote checks |
| Unfinished files | Tracked modifications, staged changes, or nonignored untracked files exist in a worktree |
| Stashes | Saved local work still needs a preservation decision |
| Unpublished tags | No configured GitHub remote preserves the tag name and direct object identity, and all relevant checks are conclusive |
| No GitHub remote | No configured remote provides a verifiable GitHub publication destination |
| Unknown | Remote, history, object availability, or local discovery checks are incomplete |
| No findings | The covered work has no review findings or unknown checks under the selected evidence mode |

Show totals for discovered repositories, inspected worktrees, projects with
findings, projects with no findings, unknown checks, audit exclusions, and
missing registered worktree paths. Exclusions and incomplete discovery must
remain visible in the coverage summary.

The picker uses worktree paths as actual selection identities, separate from
decorated display text. Findings specific to a worktree select that worktree;
repository-wide findings and unchecked branches can select the primary
existing worktree. Deduplicate entries for the same worktree. The primary
choice is the main registered worktree when it exists, otherwise the most
recently visited existing worktree, otherwise a deterministic existing path.
A repository without an existing worktree remains reportable but has no
lazygit picker target.

Selecting a row launches `lazygit -p <exact-worktree-path>`. After it exits,
reinspect that repository's refs, files, stashes, and worktree registrations
and refresh its remote evidence. Update or remove its rows according to the
current report filter. Cancellation or an empty list ends the chooser.

## Configuration and operational defaults

- Personal configuration belongs in `~/.config/my-git-utils/audit.toml`,
  independent of the existing Git log filtering configuration. Configured
  roots replace the default `~/gh`, `~/temp`, and `~/tmp` list; `--root` adds
  roots for a run. Exclusions designate projects and apply to all their
  registered worktrees.
- Recursively inspect project roots, recognize Git worktree `.git` files as
  well as ordinary repositories, and deduplicate by canonical Git common
  directory. Include hidden project directories; prune Git object metadata
  and dependency trees such as `.venv` and `node_modules`. Do not recursively
  follow directory symlinks; explicit roots, history entries, and registered
  worktrees may still identify projects through those paths.
- Read lazygit state as YAML through a small adapter. Support its current
  state directory and the older config-directory location, respecting XDG
  paths. Missing history does not prevent root discovery. Malformed or
  unreadable history is a visible discovery limitation.
- Remote checks use a configurable 30-second timeout and bounded concurrency
  of four repositories by default. They must finish without interactive
  authentication prompts. Failed checks produce diagnostics and unknown
  evidence while other repositories continue.
- In offline mode, label evidence cached and report unavailable histories or
  tag identities as inconclusive. A failed fresh check does not silently
  switch to an offline success claim.
- No-finding results are scoped to audit coverage and evidence freshness.
  Work preserved by equivalent changes after a squash merge may still produce
  review findings. Unconfigured GitHub destinations are outside verification.
- Return success when the requested report or chooser completes without
  operational failures, including reports containing ordinary review findings.
  Return a nonzero status for incomplete operational checks or invalid input,
  while retaining any useful partial report.

## Verification constraints

- A successful check of any configured GitHub remote can establish verified
  publication for a commit or tag. Absence from successfully checked remotes
  does not establish absence everywhere when another relevant check failed.
  Retain each remote failure as a visible coverage limitation.
- Inspect remote branch and tag histories. For a tag, compare its name and
  direct object identity; merely sharing the peeled target commit is not proof
  that an annotated tag itself is preserved.
- Fresh inspection must preserve local branches, local tags, the index,
  working files, and `FETCH_HEAD`. It must not use stale remote refs to claim
  verified publication. Configured fetch mappings and tag pruning must not
  redirect an audit fetch into ordinary local tags.
- Git supports explicit heads/tags refspecs into a separate namespace, with
  an empty `--refmap=` and disabled automatic tag handling. Temporary audit
  refs need cleanup because existing `git-log --all` includes refs outside
  heads/remotes namespaces. An isolated temporary Git directory is another
  available implementation approach. The exact mechanism is left to
  implementation and focused verification.
- Shallow history can falsely make an ancestor look absent from remote
  history. Detect shallow repositories and report inconclusive absence checks
  rather than automatically downloading their entire history. Positive
  publication evidence remains useful.
- Resolve effective Git URLs, including `insteadOf` rewrites and separately
  configured push URLs. Inspect named remotes and explicit branch remote or
  push-remote URLs, deduplicating destinations that identify the same GitHub
  repository. The existing PR-context URL parser handles direct GitHub HTTPS
  and SSH URLs but does not expand aliases or rewrites. Unresolved URL
  identities remain a visible verification limitation.
- Keep audit coverage independent from existing Git log display filters;
  a branch hidden in a graph may still contain local work.

These constraints are supported by a read-only source investigation and
disposable repository probes. No configured remote of an actual project was
fetched during the interview. Primary Git references:
[fetch mappings and tag handling](https://git-scm.com/docs/git-fetch),
[effective remote URLs](https://git-scm.com/docs/git-remote),
[remote refs and tag identities](https://git-scm.com/docs/git-ls-remote), and
[shallow history](https://git-scm.com/docs/shallow).

## Implementation verification

Use focused integration cases built from disposable repositories and fake
remote/chooser tools, following this package's existing testing approach.

- Discover a repository absent from lazygit history, a linked worktree outside
  the roots, duplicate paths to one common repository, explicit exclusions,
  malformed history, and missing registered paths.
- Detect an unpublished noncurrent branch and detached worktree commit, then
  clear their findings once a configured GitHub remote preserves the commits.
  Verify publication through a fork even when origin lacks the commit.
- Check independent unfinished files in two worktrees, shared stashes,
  nonignored untracked files, and exclusion of ignored outputs.
- Compare lightweight and annotated tags, including identical peeled targets
  with different annotated tag objects, name collisions, and remote deletion.
- Preserve positive publication evidence during another remote's failure;
  make unresolved absence checks unknown. Cover timeouts, shallow ancestry,
  missing objects, and cached offline evidence.
- Prove remote refresh preserves local branches, tags, index, working files,
  and `FETCH_HEAD`, and leaves no audit refs visible in ordinary Git logs after
  completion or handled failure.
- Verify default report filtering, `--all`, coverage counts, readable plain
  output, fzf selection of exact unusual paths, cancellation, and the lazygit
  return-and-refresh loop.

Run the repository's required `just test` and `just lint` checks. Installation
through `just sync` belongs to the main checkout after implementation review
and local integration, following this repository's established workflow.

## Documentation boundary

This interview records decisions and terminology in
[GLOSSARY.md](../GLOSSARY.md). The host choice follows the existing
[standalone-tool ADR](adr/0001-standalone-repo-uv-tool-install.md). The additional
choices are readily reversible and do not justify another ADR.

These are repository documents in `my-git-utils`, with no deployed dotfile
target. The initial chezmoi draft is relocated here so the utility's vocabulary
and design stay with its implementation host.
