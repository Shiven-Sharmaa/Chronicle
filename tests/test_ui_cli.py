"""`chronicle ui` end-to-end: starts the daemon if needed, waits for the
web UI's port file, and the port it reports actually serves the app."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from chronicle.daemon import is_running
from chronicle.paths import Paths


def _chronicle(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "chronicle.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _wait_for(predicate, timeout=10.0, interval=0.05):
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


def test_ui_starts_daemon_and_reports_working_url(repo: Path):
    paths = Paths.for_root(repo)

    proc = _chronicle("init", "--no-hooks", cwd=repo)
    assert proc.returncode == 0, proc.stderr

    try:
        proc = _chronicle("ui", "--no-browser", cwd=repo)
        assert proc.returncode == 0, proc.stderr
        assert "http://127.0.0.1:" in proc.stdout

        assert is_running(paths) is not None
        assert _wait_for(lambda: paths.web_port_path.exists())
        port = paths.web_port_path.read_text().strip()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
            assert resp.status == 200
    finally:
        _chronicle("daemon", "stop", cwd=repo)
