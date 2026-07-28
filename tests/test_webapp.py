from __future__ import annotations

from fastapi.testclient import TestClient

from chronicle.engine import SnapshotEngine
from chronicle.paths import Paths
from chronicle.webapp import create_app


def _client(paths: Paths) -> TestClient:
    return TestClient(create_app(paths))


def test_status_reports_snapshot_count(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="human")

    client = _client(initialized)
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot_count"] == 1
    assert body["root"] == str(initialized.root)


def test_agents_lists_distinct_agents_in_first_seen_order(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="claude-code")
    (initialized.root / "b.py").write_text("b")
    engine.capture(agent="codex")
    (initialized.root / "a.py").write_text("a2")
    engine.capture(agent="claude-code")

    client = _client(initialized)
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert [a["agent"] for a in body] == ["claude-code", "codex"]
    assert {a["agent"]: a["count"] for a in body} == {"claude-code": 2, "codex": 1}


def test_snapshots_list_and_filter_by_agent(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="claude-code")
    (initialized.root / "b.py").write_text("b")
    engine.capture(agent="codex")

    client = _client(initialized)
    r = client.get("/api/snapshots")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/api/snapshots", params={"agent": "codex"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["agent"] == "codex"
    assert body[0]["files"][0]["path"] == "b.py"
    assert body[0]["added_total"] == 1


def test_snapshots_filter_by_file(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="human")
    (initialized.root / "b.py").write_text("b")
    engine.capture(agent="human")

    client = _client(initialized)
    r = client.get("/api/snapshots", params={"file": "a.py"})
    body = r.json()
    assert len(body) == 1
    assert "a.py" in [f["path"] for f in body[0]["files"]]
    assert "b.py" not in [f["path"] for f in body[0]["files"]]


def test_snapshot_detail_and_404(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    snap_id = engine.capture(agent="human")

    client = _client(initialized)
    r = client.get(f"/api/snapshots/{snap_id}")
    assert r.status_code == 200
    assert r.json()["id"] == snap_id

    r = client.get("/api/snapshots/999999")
    assert r.status_code == 404


def test_snapshot_diff_contains_change(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("hello\n")
    snap_id = engine.capture(agent="human")

    client = _client(initialized)
    r = client.get(f"/api/snapshots/{snap_id}/diff")
    assert r.status_code == 200
    assert "hello" in r.json()["diff"]


def test_diff_between_two_snapshots(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("v1\n")
    id1 = engine.capture(agent="human")
    (initialized.root / "a.py").write_text("v2\n")
    id2 = engine.capture(agent="human")

    client = _client(initialized)
    r = client.get("/api/diff", params={"a": id1, "b": id2})
    assert r.status_code == 200
    diff = r.json()["diff"]
    assert "-v1" in diff
    assert "+v2" in diff

    r = client.get("/api/diff", params={"a": id1, "b": 999999})
    assert r.status_code == 404


def test_restore_via_api_reverts_file_and_records_snapshots(engine: SnapshotEngine, initialized: Paths):
    f = initialized.root / "a.py"
    f.write_text("v1\n")
    id1 = engine.capture(agent="human")
    f.write_text("v2\n")
    engine.capture(agent="human")
    assert f.read_text() == "v2\n"

    client = _client(initialized)
    r = client.post(f"/api/snapshots/{id1}/restore")
    assert r.status_code == 200
    body = r.json()
    assert "safety_snapshot_id" in body
    assert "restore_snapshot_id" in body

    assert f.read_text() == "v1\n"

    r = client.get(f"/api/snapshots/{body['restore_snapshot_id']}")
    assert r.json()["kind"] == "restore"
    assert r.json()["restored_from_id"] == id1


def test_restore_404_for_missing_snapshot(initialized: Paths):
    client = _client(initialized)
    r = client.post("/api/snapshots/999999/restore")
    assert r.status_code == 404


def test_blame_returns_per_line_agent(engine: SnapshotEngine, initialized: Paths):
    f = initialized.root / "shared.py"
    f.write_text("line1\n")
    engine.capture(agent="human")
    f.write_text("line1\nline2\n")
    engine.capture(agent="codex")

    client = _client(initialized)
    r = client.get("/api/blame", params={"path": "shared.py"})
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert [l["agent"] for l in lines] == ["human", "codex"]


def test_files_lists_distinct_touched_paths(engine: SnapshotEngine, initialized: Paths):
    (initialized.root / "a.py").write_text("a")
    engine.capture(agent="human")
    (initialized.root / "b.py").write_text("b")
    engine.capture(agent="human")

    client = _client(initialized)
    r = client.get("/api/files")
    files = set(r.json())
    assert {"a.py", "b.py"} <= files


def test_serves_built_frontend_if_present(initialized: Paths):
    from chronicle.webapp import STATIC_DIR

    client = _client(initialized)
    r = client.get("/")
    if STATIC_DIR.is_dir():
        assert r.status_code == 200
        assert "chronicle" in r.text.lower()
    else:
        assert r.status_code == 404
