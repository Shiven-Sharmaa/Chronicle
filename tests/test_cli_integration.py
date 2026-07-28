"""The Phase 1 'done when' demo from the build plan, run for real:

    you run Claude Code, it does `rm src/old.py` via bash, and
    `chronicle restore` brings the file back.

This drives the actual `chronicle` CLI/daemon as subprocesses (not the
library directly) so it proves the end-to-end tool works, not just the
internals.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from chronicle.daemon import is_running
from chronicle.db import connect, list_snapshots
from chronicle.paths import Paths


def _chronicle(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "chronicle.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _wait_for(predicate, timeout=8.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    return root


def _snapshot_count(paths: Paths) -> int:
    conn = connect(paths.db_path)
    try:
        return len(list_snapshots(conn))
    finally:
        conn.close()


def test_rm_via_bash_then_restore_brings_file_back(repo: Path):
    paths = Paths.for_root(repo)

    proc = _chronicle("init", cwd=repo)
    assert proc.returncode == 0, proc.stderr

    # Speed the debounce up so the test doesn't wait on the 400ms default.
    (paths.config_path).write_text(
        "[core]\n"
        "debounce_ms = 100\n"
        "max_batch_window_s = 1.0\n"
        "max_file_size_mb = 5.0\n"
        "attribution_window_s = 3.0\n"
        "group_gap_s = 60.0\n"
        'excludes = [".git", ".chronicle"]\n'
    )

    src_dir = repo / "src"
    src_dir.mkdir()
    old_file = src_dir / "old.py"

    try:
        proc = _chronicle("daemon", "start", cwd=repo)
        assert proc.returncode == 0, proc.stderr
        assert _wait_for(lambda: is_running(paths) is not None)

        baseline = _snapshot_count(paths)

        # Simulate an agent creating the file via a normal filesystem write,
        # *after* the daemon is already watching -- wait for it to capture it.
        old_file.write_text("def important():\n    return 42\n")
        assert _wait_for(lambda: _snapshot_count(paths) > baseline)

        before_delete = _snapshot_count(paths)

        # Simulate Claude Code running `rm src/old.py` via bash -- chronicle
        # has no hook here, it just sees the filesystem change.
        subprocess.run(["rm", str(old_file)], check=True)
        assert not old_file.exists()

        assert _wait_for(lambda: _snapshot_count(paths) > before_delete)

        # Find the last snapshot where old.py still existed.
        conn = connect(paths.db_path)
        try:
            rows = list_snapshots(conn, file="src/old.py")
        finally:
            conn.close()
        assert rows, "expected at least one snapshot touching src/old.py"
        # Rows are ordered newest first; the snapshot that added the file
        # (change_type 'A') is the one whose tree still contains it.
        add_snapshot_id = None
        for row in rows:
            conn = connect(paths.db_path)
            try:
                from chronicle.db import get_file_changes

                changes = get_file_changes(conn, row["id"])
            finally:
                conn.close()
            for c in changes:
                if c["path"] == "src/old.py" and c["change_type"] == "A":
                    add_snapshot_id = row["id"]
        assert add_snapshot_id is not None

        proc = _chronicle("restore", str(add_snapshot_id), cwd=repo)
        assert proc.returncode == 0, proc.stderr

        assert old_file.exists()
        assert old_file.read_text() == "def important():\n    return 42\n"

    finally:
        _chronicle("daemon", "stop", cwd=repo)
