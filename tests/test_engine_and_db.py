from __future__ import annotations

from pathlib import Path

from chronicle.db import connect, get_file_changes, get_snapshot, list_snapshots
from chronicle.engine import SnapshotEngine
from chronicle.paths import Paths


def test_capture_records_snapshot_and_file_changes(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "new.py").write_text("print(1)")
    snap_id = engine.capture(agent="human", tool=None, confidence="none")
    assert snap_id is not None

    conn = connect(initialized.db_path)
    try:
        row = get_snapshot(conn, snap_id)
        assert row["agent"] == "human"
        assert row["kind"] == "capture"
        changes = get_file_changes(conn, snap_id)
        by_path = {c["path"]: c for c in changes}
        assert "new.py" in by_path
        assert by_path["new.py"]["change_type"] == "A"
    finally:
        conn.close()


def test_capture_is_noop_when_nothing_changed(engine: SnapshotEngine):
    (engine.paths.root / "x.py").write_text("a")
    first = engine.capture()
    assert first is not None
    second = engine.capture()  # nothing changed since
    assert second is None


def test_capture_force_creates_empty_snapshot(engine: SnapshotEngine):
    snap_id = engine.capture(force=True, message="forced baseline")
    assert snap_id is not None


def test_list_snapshots_filters_by_agent(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="claude-code")
    (initialized.root / "b.py").write_text("b")
    engine.capture(agent="codex")

    conn = connect(initialized.db_path)
    try:
        claude_rows = list_snapshots(conn, agent="claude-code")
        codex_rows = list_snapshots(conn, agent="codex")
    finally:
        conn.close()

    assert len(claude_rows) == 1
    assert len(codex_rows) == 1
    assert claude_rows[0]["agent"] == "claude-code"
    assert codex_rows[0]["agent"] == "codex"


def test_parent_chain_links_snapshots(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    id1 = engine.capture()
    (initialized.root / "b.py").write_text("b")
    id2 = engine.capture()

    conn = connect(initialized.db_path)
    try:
        row2 = get_snapshot(conn, id2)
    finally:
        conn.close()
    assert row2["parent_id"] == id1
