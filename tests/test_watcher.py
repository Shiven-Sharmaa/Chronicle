from __future__ import annotations

import time

from chronicle.config import Config
from chronicle.db import connect, list_snapshots
from chronicle.paths import Paths
from chronicle.watcher import Watcher


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_watcher_collapses_burst_into_one_snapshot(initialized: Paths):
    config = Config.load(initialized.config_path)
    watcher = Watcher(initialized, config)
    watcher.start()
    try:
        # A burst of writes within the debounce window should become one snapshot.
        for i in range(10):
            (initialized.root / f"f{i}.txt").write_text(str(i))
            time.sleep(0.01)

        def one_snapshot_recorded():
            conn = connect(initialized.db_path)
            try:
                return len(list_snapshots(conn)) >= 1
            finally:
                conn.close()

        assert _wait_for(one_snapshot_recorded, timeout=5.0)
        time.sleep(0.5)  # let any stragglers flush before we count

        conn = connect(initialized.db_path)
        try:
            rows = list_snapshots(conn)
        finally:
            conn.close()
        # exactly one new snapshot beyond the (none yet -- initialized fixture
        # doesn't take a baseline snapshot itself)
        assert len(rows) == 1
        assert len(list((initialized.root).glob("f*.txt"))) == 10
    finally:
        watcher.stop()


def test_watcher_ignores_chronicle_dir(initialized: Paths):
    config = Config.load(initialized.config_path)
    watcher = Watcher(initialized, config)
    watcher.start()
    try:
        time.sleep(0.3)  # let the watcher settle
        # Writing inside .chronicle/ (e.g. our own log/db activity) must not
        # trigger a snapshot -- otherwise the daemon would snapshot itself
        # into an infinite loop.
        (initialized.chronicle_dir / "scratch.tmp").write_text("noise")
        time.sleep(1.5)

        conn = connect(initialized.db_path)
        try:
            rows = list_snapshots(conn)
        finally:
            conn.close()
        assert len(rows) == 0
    finally:
        watcher.stop()
