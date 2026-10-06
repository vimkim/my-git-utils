"""git-log-pr (glpr): git-log of HEAD, the PR head and the PR base.

Usage:
  glpr [<pr-number>|<pr-url>|<branch>] [git-log arguments] [--] [paths]

  Without a selector, uses the branch's recorded PR association or discovers its PR.
  Lines are marked "◀ HEAD", "◀ PR-HEAD" (the commit GitHub has for the PR)
  and "◀ PR-BASE" (the remote-tracking tip of the branch the PR merges into).

  The PR head is fetched only when its commit is missing locally or the
  remote-tracking ref that labels it is stale; the PR base only when its
  remote-tracking ref is missing or older than GitHub's view of the PR. The PR head is shown
  as the head repository's remote-tracking branch when such a remote exists,
  otherwise as <base-remote>/pr/<number>.

  With no PR, falls back to HEAD, its upstream and the default branch.

Examples:
  glpr
  glpr 123 -n 80
  glpr --since=2.weeks -- src/
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from rich.console import Console

from ..pr import context
from . import core, git

err = Console(stderr=True, highlight=False)

GITHUB_REPO = re.compile(r"github\.com[:/]+(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$", re.IGNORECASE)
PR_URL = re.compile(r"github\.com/(?P<repo>[^/]+/[^/]+)/pull/\d+", re.IGNORECASE)
PR_FIELDS = (
    "number,url,baseRefName,baseRefOid,headRefName,headRefOid,headRepository,headRepositoryOwner"
)


@dataclass
class PullRequest:
    number: int
    url: str
    base_repo: str
    base_name: str
    base_oid: str
    head_repo: str
    head_name: str
    head_oid: str


def note(message: str) -> None:
    err.print(f"[yellow]glpr:[/] {message}")


def view_pr(selector: str | None) -> tuple[PullRequest | None, str]:
    """Return a PR or a genuine no-match result; propagate operational errors."""
    try:
        data = context.read_pr(selector, fields=PR_FIELDS)
    except context.NoPR as exc:
        return None, str(exc)
    base = PR_URL.search(data["url"])
    owner = (data.get("headRepositoryOwner") or {}).get("login", "")
    name = (data.get("headRepository") or {}).get("name", "")
    return PullRequest(
        number=data["number"],
        url=data["url"],
        base_repo=base.group("repo") if base else "",
        base_name=data["baseRefName"],
        base_oid=data["baseRefOid"],
        head_repo=f"{owner}/{name}" if owner and name else "",
        head_name=data["headRefName"],
        head_oid=data["headRefOid"],
    ), ""


def remote_for(repo: str) -> str | None:
    """The remote whose URL points at GitHub `owner/name`."""
    for remote, url in git.remote_urls().items():
        match = GITHUB_REPO.search(url)
        if match and match.group("repo").lower() == repo.lower():
            return remote
    return None


def fetch(remote: str, source: str, dest: str) -> None:
    subprocess.run(
        ["git", "fetch", "--quiet", "--no-tags", remote, f"+{source}:{dest}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure(remote: str | None, source: str, dest: str, oid: str) -> str | None:
    """A rev for `oid`: `dest` when it is (or after fetching, becomes) current.

    Fetches only when the commit is missing or `dest` does not point at it.
    Falls back to the bare commit id when it exists locally, else None.
    """
    if git.has_object(oid) and git.ref_oid(dest) == oid:
        return dest
    if remote:
        fetch(remote, source, dest)
        if git.ref_oid(dest) == oid:
            return dest
    return oid if git.has_object(oid) else None


def ensure_base(remote: str | None, pr: PullRequest) -> str | None:
    """The PR base: its branch's remote-tracking ref.

    GitHub's baseRefOid is the base tip as of the PR's last update, not the
    branch's current tip, so it only tells whether the local copy is too old:
    fetch when the ref is missing or that commit is not local yet.
    """
    dest = f"refs/remotes/{remote}/{pr.base_name}"
    if remote and (not git.ref_oid(dest) or not git.has_object(pr.base_oid)):
        fetch(remote, f"refs/heads/{pr.base_name}", dest)
    if git.ref_oid(dest):
        return dest
    return pr.base_oid if git.has_object(pr.base_oid) else None


def pr_revs(pr: PullRequest) -> list[tuple[str, str]]:
    """[(mark, rev)] for HEAD, the PR head and the PR base."""
    base_remote = remote_for(pr.base_repo) or ("origin" if "origin" in git.remote_urls() else None)
    base = ensure_base(base_remote, pr)
    head_remote = remote_for(pr.head_repo) if pr.head_repo else None
    if head_remote:
        head = ensure(
            head_remote,
            f"refs/heads/{pr.head_name}",
            f"refs/remotes/{head_remote}/{pr.head_name}",
            pr.head_oid,
        )
    else:
        head = ensure(
            base_remote,
            f"refs/pull/{pr.number}/head",
            f"refs/remotes/{base_remote}/pr/{pr.number}",
            pr.head_oid,
        )
    revs = [("HEAD", "HEAD")]
    for mark, rev, what in (("PR-HEAD", head, "head"), ("PR-BASE", base, "base")):
        if rev:
            revs.append((mark, rev))
        else:
            note(f"PR {what} commit is not available locally; leaving it out")
    return revs


def github_default_branch(remote: str) -> str | None:
    """The default branch GitHub reports for `remote`'s repository."""
    match = GITHUB_REPO.search(git.remote_urls().get(remote, ""))
    if not match or not shutil.which("gh"):
        return None
    proc = subprocess.run(
        ["gh", "repo", "view", match.group("repo"), "--json", "defaultBranchRef"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)["defaultBranchRef"]["name"] or None
    except (ValueError, KeyError, TypeError):
        return None


def default_branch(remote: str | None) -> str | None:
    """The default branch as a ref: GitHub's answer first, then local guesses."""
    candidates = []
    if remote:
        name = github_default_branch(remote)
        if name:
            candidates.append(f"refs/remotes/{remote}/{name}")
        target = git.out("symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD").strip()
        if target:
            candidates.append(target)
        candidates += [f"refs/remotes/{remote}/{b}" for b in ("main", "master", "develop")]
    candidates += [f"refs/heads/{b}" for b in ("main", "master", "develop")]
    return next((c for c in candidates if git.ref_oid(c)), None)


def fallback_revs() -> list[tuple[str, str]]:
    """[(mark, rev)] for HEAD, its upstream and the default branch."""
    revs = [("HEAD", "HEAD")]
    branch = git.out("symbolic-ref", "--quiet", "HEAD").strip()
    upstream = git.upstream_of(branch) if branch.startswith("refs/heads/") else ""
    remote = None
    if upstream:
        revs.append(("UPSTREAM", upstream))
        remote = git.out("config", f"branch.{branch[len('refs/heads/') :]}.remote").strip()
    elif "origin" in git.remote_urls():
        remote = "origin"
    default = default_branch(remote)
    if default and default not in (branch, upstream):
        revs.append(("DEFAULT", default))
    return revs


def summary(pr: PullRequest) -> None:
    head = git.commit_of("HEAD")
    if not head:
        relation = "no HEAD commit"
    elif head == pr.head_oid:
        relation = "HEAD is the PR head"
    elif git.has_object(pr.head_oid):
        counts = git.out("rev-list", "--left-right", "--count", f"HEAD...{pr.head_oid}").split()
        ahead, behind = counts if len(counts) == 2 else ("?", "?")
        relation = f"HEAD is {ahead} ahead, {behind} behind the PR head"
    else:
        relation = "PR head commit not available locally"
    err.print(
        f"[bold]PR #{pr.number}[/] [cyan]{pr.head_name}[/] → [green]{pr.base_name}[/]"
        f"  [dim]{pr.url}[/]\n[dim]{relation}[/]"
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if not git.in_repo():
        print("git-log-pr: not a git repository", file=sys.stderr)
        return 128

    args = core.parse(argv)
    if len(args.revs) > 1:
        print(f"git-log-pr: expected one PR selector, got: {' '.join(args.revs)}", file=sys.stderr)
        return 2
    try:
        pr, reason = view_pr(args.revs[0] if args.revs else None)
    except context.LookupError as exc:
        print(f"git-log-pr: {exc}", file=sys.stderr)
        return exc.status
    if pr:
        summary(pr)
        marked_revs = pr_revs(pr)
    else:
        note(f"no PR ({reason}); showing HEAD, its upstream and the default branch")
        marked_revs = fallback_revs()

    args.marks += marked_revs
    return core.run(args.argv([rev for _, rev in marked_revs]))


if __name__ == "__main__":
    sys.exit(main())
