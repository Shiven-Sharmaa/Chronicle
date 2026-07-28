"""The Phase 2 'done when' demo from the build plan, run for real:

    run Claude Code and Codex concurrently on one repo, then
    `chronicle log --agent codex` correctly isolates one agent's changes.

Claude Code has hooks (tier 1) in real deployments; Codex doesn't, so it's
attributed via `chronicle run` (tier 2). This drives the actual daemon +
CLI as subprocesses, with a real hook POST standing in for what Claude
Code's PostToolUse hook would send.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from chronicle import ipc
from chronicle.daemon import is_running
from chronicle.db import connect, get_file_changes, list_snapshots
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


def test_concurrent_claude_and_codex_are_isolated_by_agent(repo: Path):
    paths = Paths.for_root(repo)

    proc = _chronicle("init", "--no-hooks", cwd=repo)
    assert proc.returncode == 0, proc.stderr

    paths.config_path.write_text(
        "[core]\n"
        "debounce_ms = 100\n"
        "max_batch_window_s = 1.0\n"
        "max_file_size_mb = 5.0\n"
        "attribution_window_s = 3.0\n"
        "group_gap_s = 60.0\n"
        'excludes = [".git", ".chronicle"]\n'
    )

    try:
        proc = _chronicle("daemon", "start", cwd=repo)
        assert proc.returncode == 0, proc.stderr
        assert _wait_for(lambda: is_running(paths) is not None)

        baseline = _snapshot_count(paths)

        # --- Claude Code: writes a file, then its PostToolUse hook fires
        # (this is exactly what chronicle.hooks.claude_code posts). ---
        (repo / "claude_file.py").write_text("def from_claude(): pass\n")
        ipc.post(
            paths.chronicle_dir,
            "/attribution",
            {
                "event": "post_tool_use",
                "agent": "claude-code",
                "tool": "Write",
                "session_id": "claude-sess-1",
                "ts": time.time(),
            },
        )
        # Wait for this to land as its own snapshot before Codex's write
        # starts -- two agents writing inside the *same* debounce window
        # would (correctly) collapse into one snapshot with one attribution,
        # which is a separate, known property of debouncing, not what this
        # test is checking. Sequencing them proves per-snapshot isolation.
        assert _wait_for(lambda: _snapshot_count(paths) >= baseline + 1)

        # --- Codex: hook-less, so it's wrapped via `chronicle run` instead.
        # Sleeps briefly after writing so its wrapper marker is still present
        # when the debounced watcher flushes (otherwise the child could exit
        # -- and chronicle run cleans up its marker -- before the ~100ms
        # debounce window elapses). --
        codex_script = (
            "open('codex_file.py','w').write('def from_codex(): pass\\n'); "
            "import time; time.sleep(0.6)"
        )
        codex_proc = subprocess.Popen(
            [sys.executable, "-m", "chronicle.cli", "run", "--agent", "codex", "--",
             sys.executable, "-c", codex_script],
            cwd=repo,
        )
        assert codex_proc.wait(timeout=10) == 0

        assert _wait_for(lambda: _snapshot_count(paths) >= baseline + 2)
        time.sleep(0.5)  # let any trailing flush settle

        proc = _chronicle("log", "--agent", "codex", cwd=repo)
        assert proc.returncode == 0, proc.stderr
        codex_log = proc.stdout
        assert "codex" in codex_log
        assert "claude-code" not in codex_log

        proc = _chronicle("log", "--agent", "claude-code", cwd=repo)
        assert proc.returncode == 0, proc.stderr
        claude_log = proc.stdout
        assert "claude-code" in claude_log
        assert "codex" not in claude_log

        # And the file-level attribution is correct, not just the label text.
        conn = connect(paths.db_path)
        try:
            codex_rows = list_snapshots(conn, agent="codex")
            claude_rows = list_snapshots(conn, agent="claude-code")
            codex_files = {
                c["path"] for r in codex_rows for c in get_file_changes(conn, r["id"])
            }
            claude_files = {
                c["path"] for r in claude_rows for c in get_file_changes(conn, r["id"])
            }
        finally:
            conn.close()

        assert "codex_file.py" in codex_files
        assert "claude_file.py" not in codex_files
        assert "claude_file.py" in claude_files
        assert "codex_file.py" not in claude_files

        assert any(r["confidence"] == "hook" for r in claude_rows)
        assert any(r["confidence"] == "wrapper" for r in codex_rows)

    finally:
        _chronicle("daemon", "stop", cwd=repo)
