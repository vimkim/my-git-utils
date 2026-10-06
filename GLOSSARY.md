# my-git-utils

Personal git command-line utilities. The `log` tools (`git-log`, `git-log-pick`,
`git-log-pr`) draw compact, colored `git log --graph` views that show only the
refs worth reading.

## Commits and branches

**HEAD**:
The locally checked-out commit, and the branch it is on, if any.
_Avoid_: local branch, current branch

**Upstream**:
The remote-tracking branch configured for a local branch (`@{u}`).
_Avoid_: remote HEAD branch, tracking branch

**PR head**:
The commit a pull request proposes to merge, as GitHub currently records it.
_Avoid_: remote HEAD branch, PR branch, source branch

**PR base**:
The branch a pull request merges into.
_Avoid_: PR target, target branch, base branch

## Pull-request context

**PR association**:
A recorded link between a local branch and a specific pull request.
It persists until explicitly replaced or cleared, even if the pull request closes.
_Avoid_: PR cache, inferred PR

**PR discovery**:
Finding the pull request related to a local checkout when no PR association or
explicit selection is available.
_Avoid_: PR association

## Display

**Label**:
A ref name decorated next to a commit in the graph.
_Avoid_: decoration, tag (a tag is a kind of ref)

**Mark**:
A `◀ NAME` annotation appended to a commit's line to point out a chosen commit.
_Avoid_: label, pin

**Hidden ref**:
A ref pruned from broad revision options (`--all`, `--branches`, `--remotes`,
`--glob`) by the configured filters; a ref named explicitly is never hidden.
_Avoid_: excluded ref, filtered branch
