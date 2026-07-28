"""Thin subprocess wrapper around git, scoped to a --git-dir/--work-tree pair.

We use plain `git` via subprocess rather than pygit2: it's zero extra
compiled-dependency risk, and every operation we need (add, commit, diff,
ls-tree, checkout, worktree) is a normal porcelain/plumbing command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str):
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}"
        )


class Git:
    """Runs `git --git-dir=<git_dir> --work-tree=<work_tree> <args...>`."""

    def __init__(self, git_dir: Path, work_tree: Path):
        self.git_dir = git_dir
        self.work_tree = work_tree

    def run(
        self,
        args: list[str],
        *,
        input: str | None = None,
        check: bool = True,
        env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        base = [
            "git",
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.work_tree}",
        ]
        proc = subprocess.run(
            base + args,
            cwd=self.work_tree,
            input=input,
            capture_output=True,
            text=True,
            env=env,
        )
        if check and proc.returncode != 0:
            raise GitError(args, proc.returncode, proc.stderr)
        return proc

    def text(self, args: list[str], **kwargs) -> str:
        return self.run(args, **kwargs).stdout.strip()
