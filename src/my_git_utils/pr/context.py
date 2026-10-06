"""Resolve PR context without confusing local branch names with GitHub branches."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urlsplit

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?", re.I
)
DEFAULT_FIELDS = "number,url,title,state,baseRefName,headRefName,headRefOid"


class LookupError(RuntimeError):
    """An operational Git or GitHub lookup failure."""

    status = 3


class ContextError(LookupError):
    """Invalid invocation context or recorded configuration."""

    status = 2


class NoPR(LookupError):
    """Discovery completed successfully with no matching PR."""

    status = 1


class AmbiguousPR(ContextError):
    """Discovery found multiple equally eligible PRs."""


def run(*args: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    except FileNotFoundError as exc:
        raise LookupError(f"required command is missing: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LookupError(f"{args[0]} timed out after 45 seconds") from exc
    if result.returncode not in allowed:
        raise LookupError(result.stderr.strip() or f"{args[0]} failed ({result.returncode})")
    return result


def gh_json(*args: str):
    try:
        return json.loads(run("gh", *args).stdout)
    except json.JSONDecodeError as exc:
        raise LookupError("gh returned invalid JSON") from exc


def config(key: str, *, local: bool = False) -> str:
    scope = ["--local"] if local else []
    result = run("git", "config", *scope, "--get", key, allowed=(0, 1))
    return result.stdout.strip()


def branch() -> str:
    if run("git", "rev-parse", "--is-inside-work-tree", allowed=(0, 128)).stdout.strip() != "true":
        raise ContextError("not inside a Git worktree; provide an explicit PR selector")
    name = run("git", "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1)).stdout.strip()
    if not name:
        raise ContextError("detached HEAD; provide an explicit PR selector")
    return name


def canonical_url(value: str, repo: str | None = None) -> str:
    match = URL.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ContextError("expected a GitHub PR URL: https://github.com/OWNER/REPO/pull/N")
    slug, number = match.groups()
    if repo and slug.casefold() != repo.casefold():
        raise ContextError(f"PR belongs to repository {slug}, expected {repo}")
    return f"https://github.com/{slug}/pull/{number}"


def metadata_url(data, repo: str | None = None) -> str:
    if not isinstance(data, dict) or "url" not in data:
        raise LookupError("gh returned invalid PR metadata")
    return canonical_url(data["url"], repo)


def remote_repository(remote: str) -> str | None:
    if not remote or remote == ".":
        return None
    remote = config(f"remote.{remote}.url") or remote
    if remote.startswith("git@github.com:"):
        slug = remote.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(remote)
        if parsed.hostname != "github.com" or parsed.scheme not in ("https", "ssh"):
            return None
        slug = parsed.path.lstrip("/")
    slug = slug.rstrip("/").removesuffix(".git")
    return slug if REPOSITORY.fullmatch(slug) else None


def repository_context(repo: str | None) -> tuple[str, str]:
    args = [repo] if repo else []
    data = gh_json("repo", "view", *args, "--json", "nameWithOwner,defaultBranchRef")
    try:
        slug = data["nameWithOwner"]
        default = (data.get("defaultBranchRef") or {}).get("name", "")
        if not isinstance(slug, str) or not REPOSITORY.fullmatch(slug):
            raise ValueError
        if not isinstance(default, str):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise LookupError("gh returned invalid repository metadata") from exc
    return slug, default


def candidates(repo: str, ref: str, head_repo: str | None, state: str) -> list[str]:
    # Filter by head ref on the server, including when its fork owner is unknown.
    # A cursor-based query avoids scanning every historical PR in the repository.
    states = "OPEN" if state == "open" else "CLOSED, MERGED"
    query = """query($owner: String!, $name: String!, $ref: String!, $endCursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequests(first: 100, after: $endCursor, headRefName: $ref, states: [STATES]) {
          nodes { url headRefName headRepository { nameWithOwner }
                  headRepositoryOwner { login } }
          pageInfo { hasNextPage endCursor }
        }
      }
    }""".replace("STATES", states)
    owner, name = repo.split("/")
    pages = gh_json(
        "api",
        "graphql",
        "--paginate",
        "--slurp",
        "-f",
        f"query={query}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-f",
        f"ref={ref}",
    )
    if not isinstance(pages, list):
        raise LookupError("gh returned invalid paginated pull-request metadata")
    urls = []
    for page in pages:
        try:
            nodes = page["data"]["repository"]["pullRequests"]["nodes"]
            if page.get("errors") or not isinstance(nodes, list):
                raise ValueError
            for item in nodes:
                if item["headRefName"] != ref:
                    continue
                slug = (item.get("headRepository") or {}).get("nameWithOwner", "")
                head_owner = (item.get("headRepositoryOwner") or {}).get("login", "")
                if head_repo:
                    if "/" in head_repo and slug.casefold() != head_repo.casefold():
                        continue
                    if "/" not in head_repo and head_owner.casefold() != head_repo.casefold():
                        continue
                url = canonical_url(item["url"], repo)
                if url not in urls:
                    urls.append(url)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise LookupError("gh returned invalid pull-request metadata") from exc
    return urls


def discover(repo: str, ref: str, head_repo: str | None) -> str | None:
    for state in ("open", "closed"):
        urls = candidates(repo, ref, head_repo, state)
        if len(urls) > 1:
            raise AmbiguousPR("multiple matching PRs; select one explicitly:\n" + "\n".join(urls))
        if urls:
            return urls[0]
    return None


def resolve_url(selector: str | None = None, repo: str | None = None) -> str:
    if repo and not REPOSITORY.fullmatch(repo):
        raise ContextError("--repo must be OWNER/REPO")
    if selector:
        if selector.startswith("https://"):
            return canonical_url(selector, repo)
        if selector.isdecimal():
            if int(selector) < 1:
                raise ContextError("PR number must be positive")
            args = ["--repo", repo] if repo else []
            data = gh_json("pr", "view", selector, *args, "--json", "url")
            return metadata_url(data, repo)
        base_repo, _ = repository_context(repo)
        owner, separator, ref = selector.partition(":")
        head_repo = owner if separator else None
        url = discover(base_repo, ref if separator else selector, head_repo)
        if url:
            return url
        raise NoPR(f"no pull requests found for selector {selector!r}")

    name = branch()
    association = config(f"branch.{name}.pr-url", local=True)
    if association:
        return canonical_url(association, repo)
    base_repo, default = repository_context(repo)
    tracking_remote = config(f"branch.{name}.remote")
    tracking_ref = config(f"branch.{name}.merge").removeprefix("refs/heads/")
    tracking_repo = remote_repository(tracking_remote)
    if tracking_repo and tracking_ref and tracking_ref != default:
        url = discover(base_repo, tracking_ref, tracking_repo)
        if url:
            return url
    # Without a known publishing remote, local names can legitimately belong
    # to forks. Query the receiving repository and filter by the exact ref.
    publishing = config(f"branch.{name}.pushRemote") or config("remote.pushDefault")
    head_repo = (
        remote_repository(publishing)
        if publishing
        else (tracking_repo if tracking_ref != default else None)
    )
    if (name, head_repo) != (tracking_ref, tracking_repo):
        url = discover(base_repo, name, head_repo)
        if url:
            return url
    raise NoPR(f"no pull requests found for local branch {name!r}")


def read_pr(selector: str | None = None, repo: str | None = None, fields: str = DEFAULT_FIELDS):
    url = resolve_url(selector, repo)
    if fields == "url":
        return {"url": url}
    data = gh_json("pr", "view", url, "--json", fields)
    if not isinstance(data, dict):
        raise LookupError("gh returned invalid PR metadata")
    return data


def info_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the current branch's PR or an explicit PR."
    )
    parser.add_argument("selector", nargs="?")
    parser.add_argument("--repo", help="receiving GitHub repository: OWNER/REPO")
    parser.add_argument("--json", default=DEFAULT_FIELDS, metavar="FIELDS")
    parser.add_argument("--jq", "-q", help="filter the JSON output using jq")
    args = parser.parse_args(argv)
    try:
        data = read_pr(args.selector, args.repo, args.json)
        output = json.dumps(data)
        if args.jq:
            try:
                proc = subprocess.run(
                    ["jq", "-r", args.jq], input=output, capture_output=True, text=True, timeout=45
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise LookupError(
                    "jq is required for --jq and must complete within 45 seconds"
                ) from exc
            if proc.returncode:
                raise ContextError(proc.stderr.strip() or "jq filter failed")
            print(proc.stdout, end="")
        else:
            print(output)
        return 0
    except LookupError as exc:
        print(f"gh-pr-info: {exc}", file=sys.stderr)
        return exc.status


def associate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly associate the current branch with a PR."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="GitHub PR URL; validated online before recording")
    group.add_argument(
        "--clear", action="store_true", help="remove the current branch's association"
    )
    args = parser.parse_args(argv)
    try:
        name = branch()
        key = f"branch.{name}.pr-url"
        if args.clear:
            run("git", "config", "--local", "--unset-all", key, allowed=(0, 5))
            print(f"Cleared PR association for {name}")
        else:
            url = canonical_url(args.url)
            data = gh_json("pr", "view", url, "--json", "url")
            canonical = metadata_url(data)
            if canonical.casefold() != url.casefold():
                raise ContextError("GitHub returned a different PR; association was not changed")
            run("git", "config", "--local", "--replace-all", key, canonical)
            print(canonical)
        return 0
    except LookupError as exc:
        print(f"gh-pr-associate: {exc}", file=sys.stderr)
        return exc.status


if __name__ == "__main__":
    sys.exit(info_main())
