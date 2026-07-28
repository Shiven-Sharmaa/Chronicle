from __future__ import annotations

from pathlib import Path

from chronicle.paths import Paths
from chronicle.store import ShadowStore


def test_init_creates_store(project: Path):
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle"])
    assert store.is_initialized()
    assert (paths.store_dir / "info" / "exclude").exists()


def test_commit_snapshot_captures_new_file(project: Path):
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle"])

    (project / "a.txt").write_text("hello")
    sha1 = store.commit_snapshot("first")
    assert sorted(store.ls_tree(sha1)) == [".gitignore", "a.txt"]

    (project / "b.txt").write_text("world")
    sha2 = store.commit_snapshot("second")
    assert sorted(store.ls_tree(sha2)) == [".gitignore", "a.txt", "b.txt"]

    changes = store.name_status(sha1, sha2)
    assert changes == [("A", "b.txt")]


def test_excludes_are_respected(project: Path):
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle", "node_modules"])

    (project / "node_modules").mkdir()
    (project / "node_modules" / "pkg.js").write_text("junk")
    (project / "real.py").write_text("code")

    sha = store.commit_snapshot("snap")
    assert sorted(store.ls_tree(sha)) == [".gitignore", "real.py"]


def test_gitignore_is_respected(project: Path):
    # project fixture ships a .gitignore with *.log and build/
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle"])

    (project / "debug.log").write_text("noise")
    (project / "build").mkdir()
    (project / "build" / "out.bin").write_text("bin")
    (project / "main.py").write_text("code")

    sha = store.commit_snapshot("snap")
    files = store.ls_tree(sha)
    assert "main.py" in files
    assert ".gitignore" in files
    assert "debug.log" not in files
    assert "build/out.bin" not in files


def test_restore_worktree_deletes_and_recreates(project: Path):
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle"])

    (project / "keep.py").write_text("v1")
    (project / "doomed.py").write_text("will be deleted")
    sha_before = store.commit_snapshot("before")

    (project / "doomed.py").unlink()
    (project / "keep.py").write_text("v2")
    store.commit_snapshot("after deletion")  # HEAD tree == worktree now

    store.restore_worktree_to(sha_before)

    assert (project / "doomed.py").exists()
    assert (project / "doomed.py").read_text() == "will be deleted"
    assert (project / "keep.py").read_text() == "v1"


def test_restore_is_append_only(project: Path):
    """Restoring must not rewrite history -- old commits stay reachable."""
    paths = Paths.for_root(project)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init([".git", ".chronicle"])

    (project / "f.txt").write_text("1")
    sha1 = store.commit_snapshot("s1")
    (project / "f.txt").write_text("2")
    sha2 = store.commit_snapshot("s2")

    store.restore_worktree_to(sha1)
    sha3 = store.commit_snapshot("restore commit")

    assert sha3 != sha2
    assert store.parent_sha(sha3) == sha2  # new commit, linear, nothing discarded
    # sha1 and sha2 still exist as real objects
    assert sorted(store.ls_tree(sha1)) == [".gitignore", "f.txt"]
    assert sorted(store.ls_tree(sha2)) == [".gitignore", "f.txt"]
