"""Exclusion logic: static excludes + the user's own .gitignore.

We never reimplement gitignore semantics (they're subtler than they look --
negation, directory-only patterns, anchoring). Instead we shell out to
`git check-ignore --stdin`, batching all candidate paths in one call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath


def is_statically_excluded(rel_path: str, excludes: list[str]) -> bool:
    """True if any path component matches a static exclude name (e.g. '.git')."""
    parts = PurePosixPath(rel_path).parts
    return any(part in excludes for part in parts)


def filter_gitignored(root: Path, rel_paths: list[str]) -> set[str]:
    """Return the subset of rel_paths that git considers ignored.

    Uses `git check-ignore --stdin` against the *project's* real git repo
    (root/.git), if one exists. If there's no .git repo, nothing is
    considered gitignored here -- static excludes still apply separately.
    """
    if not rel_paths:
        return set()
    if not (root / ".git").exists():
        return set()

    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=root,
        input="\n".join(rel_paths) + "\n",
        capture_output=True,
        text=True,
    )
    # check-ignore exits 1 when *no* paths matched, which is not an error for us.
    if proc.returncode not in (0, 1):
        return set()
    return {line for line in proc.stdout.splitlines() if line}


def is_too_large(path: Path, max_file_size_mb: float) -> bool:
    try:
        return path.stat().st_size > max_file_size_mb * 1024 * 1024
    except OSError:
        return False
