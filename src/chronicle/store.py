"""The shadow git store: every snapshot is a commit in .chronicle/store,
a git dir entirely separate from the project's own .git. The user's
`git log` never sees any of this.

History here is append-only by design. `restore`/`revert` never rewrite or
reset existing commits -- they compute a target tree and commit it as a new
snapshot, the same way `git revert` adds a new commit rather than rewriting
history. That's what makes "the undo must itself be undoable" true for free.
"""

from __future__ import annotations

import re
from pathlib import Path

from chronicle.gitutil import Git

# The well-known hash of an empty git tree object. Valid in any repo -- it's
# content-addressed, not repo-specific. Used as the "parent" of the first
# snapshot when diffing/showing it.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: (\d+))?$")


def _parse_line_porcelain(text: str) -> list[tuple[str, str]]:
    """[(commit_sha, line_content), ...] from `git blame --line-porcelain` output."""
    lines = text.split("\n")
    result: list[tuple[str, str]] = []
    i, n = 0, len(lines)
    current_sha = None
    while i < n:
        m = _BLAME_HEADER_RE.match(lines[i])
        if m:
            current_sha = m.group(1)
            i += 1
            while i < n and not lines[i].startswith("\t"):
                i += 1
            if i < n:
                result.append((current_sha, lines[i][1:]))
                i += 1
        else:
            i += 1
    return result

CHRONICLE_AUTHOR_NAME = "chronicle"
CHRONICLE_AUTHOR_EMAIL = "chronicle@localhost"


class ShadowStore:
    def __init__(self, store_dir: Path, work_tree: Path):
        self.store_dir = store_dir
        self.work_tree = work_tree
        self.git = Git(git_dir=store_dir, work_tree=work_tree)

    # ---- setup -----------------------------------------------------------

    def is_initialized(self) -> bool:
        return (self.store_dir / "HEAD").exists()

    def init(self, excludes: list[str]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.git.run(["init", "--quiet", "--initial-branch=main"])
        # Local-only identity so commits never depend on (or pollute) the
        # user's global git config.
        self.git.run(["config", "user.name", CHRONICLE_AUTHOR_NAME])
        self.git.run(["config", "user.email", CHRONICLE_AUTHOR_EMAIL])
        # Never let gc silently drop snapshots we still reference only via
        # refs/chronicle/snap/*.
        self.git.run(["config", "gc.auto", "0"])
        self._write_exclude_file(excludes)

    def _write_exclude_file(self, excludes: list[str]) -> None:
        info_dir = self.store_dir / "info"
        info_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"/{e}" for e in excludes] + [f"{e}/" for e in excludes]
        (info_dir / "exclude").write_text("\n".join(lines) + "\n")

    # ---- head / refs -------------------------------------------------------

    def head_sha(self) -> str | None:
        proc = self.git.run(["rev-parse", "--verify", "-q", "HEAD"], check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def create_ref(self, snapshot_id: int, sha: str) -> None:
        """Pin a snapshot forever, independent of what HEAD does later."""
        self.git.run(["update-ref", f"refs/chronicle/snap/{snapshot_id}", sha])

    # ---- snapshotting ------------------------------------------------------

    def stage_all(self) -> None:
        """Stage everything, respecting the exclude file + work tree .gitignore."""
        self.git.run(["add", "-A"])

    def has_staged_changes(self) -> bool:
        proc = self.git.run(["diff", "--cached", "--quiet"], check=False)
        return proc.returncode != 0

    def commit_staged(self, message: str) -> str:
        """Commit whatever is currently staged (even if nothing is)."""
        self.git.run(["commit", "--allow-empty", "--quiet", "-m", message])
        return self.head_sha()  # type: ignore[return-value]

    def commit_snapshot(self, message: str) -> str:
        """Stage everything and commit, even if nothing changed."""
        self.stage_all()
        return self.commit_staged(message)

    # ---- reading -------------------------------------------------------

    def parent_sha(self, sha: str) -> str | None:
        proc = self.git.run(["rev-parse", "-q", "--verify", f"{sha}^"], check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def name_status(self, base: str | None, target: str) -> list[tuple[str, str]]:
        """[(change_type, path), ...] between base and target.
        base=None compares against the empty tree (i.e. this is a root commit)."""
        base_ref = base or EMPTY_TREE_SHA
        out = self.git.text(["diff", "--name-status", base_ref, target])
        changes = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            change_type, path = parts[0], parts[-1]
            changes.append((change_type[0], path))
        return changes

    def numstat(self, base: str | None, target: str) -> dict[str, tuple[int, int]]:
        """path -> (added, removed) between base and target."""
        base_ref = base or EMPTY_TREE_SHA
        out = self.git.text(["diff", "--numstat", base_ref, target])
        result = {}
        for line in out.splitlines():
            if not line.strip():
                continue
            added, removed, path = line.split("\t")
            result[path] = (
                0 if added == "-" else int(added),
                0 if removed == "-" else int(removed),
            )
        return result

    def diff_text(self, a: str, b: str) -> str:
        return self.git.text(["diff", a, b])

    def show_text(self, sha: str) -> str:
        parent = self.parent_sha(sha)
        return self.diff_text(parent or EMPTY_TREE_SHA, sha)

    def ls_tree(self, sha: str) -> list[str]:
        out = self.git.text(["ls-tree", "-r", "--name-only", sha])
        return [line for line in out.splitlines() if line]

    def blame(self, rel_path: str, sha: str | None = None) -> list[tuple[str, str]]:
        """[(commit_sha, line_content), ...] for rel_path as of `sha` (default
        HEAD). Cheap to build: every snapshot is already a real commit, so
        this is exactly `git blame` against the shadow store."""
        target = sha or self.head_sha()
        out = self.git.text(["blame", "--line-porcelain", target, "--", rel_path])
        return _parse_line_porcelain(out)

    def file_at(self, sha: str, rel_path: str) -> bytes | None:
        proc = self.git.run(["show", f"{sha}:{rel_path}"], check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.encode()

    # ---- restore (append-only) ---------------------------------------------

    def restore_worktree_to(self, target_sha: str) -> None:
        """Make the working tree exactly match target_sha's tree.

        Assumes the caller has just taken a safety snapshot, so HEAD's tree
        currently equals the working tree exactly -- that's what lets us
        compute "files to delete" as a simple set difference instead of
        walking the live filesystem.
        """
        current_sha = self.head_sha()
        current_files = set(self.ls_tree(current_sha)) if current_sha else set()
        target_files = set(self.ls_tree(target_sha))

        for rel_path in current_files - target_files:
            fp = self.work_tree / rel_path
            if fp.exists() or fp.is_symlink():
                fp.unlink()
        self._prune_empty_dirs(current_files - target_files)

        if target_files:
            self.git.run(["checkout", target_sha, "--", "."])

    def _prune_empty_dirs(self, removed_paths: set[str]) -> None:
        dirs = set()
        for rel_path in removed_paths:
            dirs.add((self.work_tree / rel_path).parent)
        # Deepest first so nested empty dirs collapse correctly.
        for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
            while d != self.work_tree and d.exists() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent

    # ---- bisect worktrees ---------------------------------------------------

    def add_worktree(self, dest: Path, sha: str) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.git.run(["worktree", "add", "--detach", "--quiet", str(dest), sha])

    def remove_worktree(self, dest: Path) -> None:
        self.git.run(["worktree", "remove", "--force", str(dest)], check=False)
