from __future__ import annotations

from chronicle.db import connect, get_snapshot_by_sha
from chronicle.engine import SnapshotEngine
from chronicle.paths import Paths


def test_blame_attributes_each_line_to_its_agent(engine: SnapshotEngine, initialized: Paths):
    f = initialized.root / "shared.py"

    f.write_text("line_by_human\n")
    engine.capture(agent="human", confidence="none")

    f.write_text("line_by_human\nline_by_claude\n")
    engine.capture(agent="claude-code", confidence="hook")

    f.write_text("line_by_human\nline_by_claude\nline_by_codex\n")
    engine.capture(agent="codex", confidence="wrapper")

    store = engine.store
    lines = store.blame("shared.py")
    assert [content for _, content in lines] == [
        "line_by_human",
        "line_by_claude",
        "line_by_codex",
    ]

    conn = connect(initialized.db_path)
    try:
        agents = []
        for sha, _ in lines:
            row = get_snapshot_by_sha(conn, sha)
            agents.append(row["agent"])
    finally:
        conn.close()

    assert agents == ["human", "claude-code", "codex"]


def test_blame_as_of_earlier_snapshot(engine: SnapshotEngine, initialized: Paths):
    f = initialized.root / "shared.py"
    f.write_text("v1\n")
    first_id = engine.capture(agent="human")
    conn = connect(initialized.db_path)
    try:
        from chronicle.db import get_snapshot

        first_sha = get_snapshot(conn, first_id)["commit_sha"]
    finally:
        conn.close()

    f.write_text("v1\nv2\n")
    engine.capture(agent="codex")

    lines_now = engine.store.blame("shared.py")
    assert len(lines_now) == 2

    lines_then = engine.store.blame("shared.py", sha=first_sha)
    assert len(lines_then) == 1
    assert lines_then[0][1] == "v1"
