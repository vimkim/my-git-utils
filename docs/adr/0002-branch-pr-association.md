# Separate branch PR associations from live discovery

A review branch can have a different name from the GitHub branch and can
remain useful after the PR closes. Store its explicit PR association as a
canonical URL in repository-local branch configuration, separate from
read-only discovery and live PR metadata. This permits offline URL lookup
and preserves associations through branch renaming while avoiding directory
bindings that silently survive switching to an unrelated branch.

Discovery prefers a unique open PR, then a unique historical PR, and reports
ambiguity instead of choosing arbitrarily. It does not infer from detached
commits or directory names and does not automatically write an association.

The shared resolver belongs to this generic Git-tool distribution; personal
wrappers and CUBRID-specific consumers use that interface so lookup rules do
not drift across commands.
