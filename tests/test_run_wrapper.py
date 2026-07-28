from __future__ import annotations

import sys
import time

from chronicle.attribution import AttributionTracker
from chronicle.config import Config
from chronicle.db import connect, list_snapshots
from chronicle.paths import Paths
from chronicle.run_wrapper import run
from chronicle.watcher import Watcher


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_run_wrapper_attributes_snapshot_to_wrapped_agent(initialized: Paths):
    config = Config.load(initialized.config_path)
    tracker = AttributionTracker(config.attribution_window_s)
    watcher = Watcher(initialized, config, tracker=tracker)
    watcher.start()
    try:
        # Writes a file, then stays alive briefly so the marker file is
        # still present when the debounced watcher flushes.
        script = "open('wrapped.txt','w').write('hi'); import time; time.sleep(0.6)"
        exit_code = run(initialized, "codex", [sys.executable, "-c", script])
        assert exit_code == 0

        def captured():
            conn = connect(initialized.db_path)
            try:
                rows = list_snapshots(conn)
            finally:
                conn.close()
            return any(r["agent"] == "codex" for r in rows)

        assert _wait_for(captured)
    finally:
        watcher.stop()

    conn = connect(initialized.db_path)
    try:
        rows = list_snapshots(conn)
    finally:
        conn.close()
    codex_rows = [r for r in rows if r["agent"] == "codex"]
    assert len(codex_rows) >= 1
    assert codex_rows[0]["confidence"] == "wrapper"


def test_run_wrapper_cleans_up_marker_after_exit(initialized: Paths):
    from chronicle import attribution

    run(initialized, "codex", [sys.executable, "-c", "pass"])
    assert attribution._active_wrappers(initialized.chronicle_dir) == []


def test_run_wrapper_returns_child_exit_code(initialized: Paths):
    exit_code = run(initialized, "codex", [sys.executable, "-c", "import sys; sys.exit(7)"])
    assert exit_code == 7
