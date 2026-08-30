"""Thin git wrappers used to build the counterfactual worktree.

The whole tool rests on one trick: check out the base commit somewhere else,
apply *only* the test changes there, and run the tests. Nothing in here ever
writes to the user's working tree.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Sequence

# Written by `git diff` when a side of the comparison has no blob.
NULL_BLOB = "/dev/null"

# The well-known hash of git's empty tree, used as a base when a repository
# has no commits at all.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

DEFAULT_BRANCH_CANDIDATES = (
    "origin/HEAD",
    "origin/main",
    "origin/master",
    "main",
    "master",
)


class GitError(RuntimeError):
    """A git invocation failed."""


def git(
    *args: str,
    cwd: Path | str | None = None,
    check: bool = True,
) -> str:
    """Run a git command and return its stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def repo_root(cwd: Path | str | None = None) -> Path:
    """Absolute path to the enclosing repository's top level."""
    return Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip())


def rev_parse(ref: str, cwd: Path | str | None = None) -> str:
    """Resolve a ref to a full object id, or raise GitError."""
    return git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd).strip()


def has_commits(cwd: Path | str | None = None) -> bool:
    try:
        rev_parse("HEAD", cwd=cwd)
    except GitError:
        return False
    return True


def tracked_changes(cwd: Path | str | None = None) -> list[str]:
    """Paths with staged or unstaged modifications, relative to the repo root."""
    out = git("status", "--porcelain=v1", "--untracked-files=no", cwd=cwd)
    paths: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # Format is "XY path" or "XY old -> new" for renames.
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip().strip('"'))
    return paths


def untracked_files(cwd: Path | str | None = None) -> list[str]:
    out = git(
        "ls-files", "--others", "--exclude-standard", cwd=cwd
    )
    return [line for line in out.splitlines() if line.strip()]


def resolve_base(cwd: Path | str | None = None) -> tuple[str, str]:
    """Pick what to compare against, and explain the choice.

    Uncommitted work is the common case for someone reviewing a change an
    agent just made, so that wins: compare the working tree against HEAD.
    Otherwise fall back to the merge base with the default branch, which is
    what you want when the change is already a series of commits on a branch.
    """
    if not has_commits(cwd=cwd):
        return EMPTY_TREE, "repository has no commits; comparing against the empty tree"

    if tracked_changes(cwd=cwd):
        return rev_parse("HEAD", cwd=cwd), "uncommitted changes present; comparing against HEAD"

    for candidate in DEFAULT_BRANCH_CANDIDATES:
        try:
            resolved = rev_parse(candidate, cwd=cwd)
        except GitError:
            continue
        head = rev_parse("HEAD", cwd=cwd)
        if resolved == head:
            continue
        merge_base = git("merge-base", head, resolved, cwd=cwd, check=False).strip()
        if merge_base:
            return merge_base, f"comparing against merge-base with {candidate}"

    try:
        return rev_parse("HEAD~1", cwd=cwd), "comparing against HEAD~1"
    except GitError:
        # A clean tree with nothing to compare against has nothing to check.
        # Saying so beats diffing the whole repository against the empty tree
        # and treating every existing file as part of the change.
        return rev_parse("HEAD", cwd=cwd), "clean tree with no earlier commit"


def changed_files(base: str, cwd: Path | str | None = None) -> list[str]:
    """Files that differ between `base` and the current working tree."""
    out = git("diff", "--name-only", "--diff-filter=d", base, "--", cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def diff_patch(
    base: str,
    paths: Sequence[str],
    cwd: Path | str | None = None,
) -> str:
    """A patch taking `base` to the working tree, restricted to `paths`."""
    if not paths:
        return ""
    return git(
        "diff",
        "--binary",
        "--no-color",
        base,
        "--",
        *paths,
        cwd=cwd,
    )


def apply_patch(patch: str, cwd: Path | str) -> None:
    """Apply a patch inside `cwd`, raising GitError with git's own message."""
    if not patch.strip():
        return
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=str(cwd),
        input=patch,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"could not apply the test-only patch: {proc.stderr.strip()}")


@contextlib.contextmanager
def counterfactual_worktree(
    base: str,
    repo: Path | str,
) -> Iterator[Path]:
    """Check `base` out into a scratch directory, and clean it up afterwards.

    The user's own worktree is never touched.
    """
    repo = Path(repo)
    parent = Path(tempfile.mkdtemp(prefix="falsify-"))
    target = parent / "counterfactual"
    added = False
    try:
        if base == EMPTY_TREE:
            # `git worktree add` needs a commit, and the empty tree is not one.
            # An empty repository is the same thing for our purposes.
            target.mkdir()
            git("init", "--quiet", str(target))
        else:
            git("worktree", "add", "--detach", "--quiet", str(target), base, cwd=repo)
            added = True
        yield target
    finally:
        if added:
            # --force because we deliberately dirtied it with the patch.
            git("worktree", "remove", "--force", str(target), cwd=repo, check=False)
            git("worktree", "prune", cwd=repo, check=False)
        shutil.rmtree(parent, ignore_errors=True)
