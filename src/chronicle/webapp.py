"""The JSON API behind the web UI, plus serving the built frontend.

Runs over plain TCP on 127.0.0.1 (unlike the tier-1 attribution endpoint in
httpapi.py, which stays on a Unix socket) -- a browser can't open a UDS
connection, so the UI needs a real port. Both servers run side by side
inside the daemon process; see webserver.py for how this one is launched.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from chronicle.db import (
    connect,
    get_file_changes,
    get_snapshot,
    get_snapshot_by_sha,
    list_snapshots,
)
from chronicle.engine import SnapshotEngine
from chronicle.paths import Paths
from chronicle.store import ShadowStore

STATIC_DIR = Path(__file__).parent / "webui_dist"


def _snapshot_json(conn, row) -> dict:
    changes = get_file_changes(conn, row["id"])
    return {
        "id": row["id"],
        "commit_sha": row["commit_sha"],
        "parent_id": row["parent_id"],
        "ts": row["ts"],
        "agent": row["agent"] or "unknown",
        "session_id": row["session_id"],
        "tool": row["tool"],
        "confidence": row["confidence"],
        "kind": row["kind"],
        "restored_from_id": row["restored_from_id"],
        "prompt_text": row["prompt_text"],
        "files": [
            {
                "path": c["path"],
                "change_type": c["change_type"],
                "added": c["added"] or 0,
                "removed": c["removed"] or 0,
            }
            for c in changes
        ],
        "added_total": sum(c["added"] or 0 for c in changes),
        "removed_total": sum(c["removed"] or 0 for c in changes),
    }


def create_app(paths: Paths) -> FastAPI:
    app = FastAPI(title="chronicle", docs_url=None, redoc_url=None)

    @app.get("/api/status")
    def status():
        conn = connect(paths.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        finally:
            conn.close()
        return {"root": str(paths.root), "snapshot_count": count}

    @app.get("/api/agents")
    def agents():
        conn = connect(paths.db_path)
        try:
            rows = conn.execute(
                "SELECT agent, COUNT(*) AS n FROM snapshots "
                "WHERE agent IS NOT NULL GROUP BY agent ORDER BY MIN(id)"
            ).fetchall()
        finally:
            conn.close()
        return [{"agent": r["agent"], "count": r["n"]} for r in rows]

    @app.get("/api/snapshots")
    def snapshots(
        agent: str | None = None,
        file: str | None = None,
        since_ts: float | None = None,
        limit: int = 200,
    ):
        conn = connect(paths.db_path)
        try:
            rows = list_snapshots(conn, agent=agent, since_ts=since_ts, file=file, limit=limit)
            return [_snapshot_json(conn, r) for r in rows]
        finally:
            conn.close()

    @app.get("/api/snapshots/{snapshot_id}")
    def snapshot_detail(snapshot_id: int):
        conn = connect(paths.db_path)
        try:
            row = get_snapshot(conn, snapshot_id)
            if row is None:
                raise HTTPException(404, f"no such snapshot: {snapshot_id}")
            return _snapshot_json(conn, row)
        finally:
            conn.close()

    @app.get("/api/snapshots/{snapshot_id}/diff")
    def snapshot_diff(snapshot_id: int):
        conn = connect(paths.db_path)
        try:
            row = get_snapshot(conn, snapshot_id)
            if row is None:
                raise HTTPException(404, f"no such snapshot: {snapshot_id}")
            sha = row["commit_sha"]
        finally:
            conn.close()
        store = ShadowStore(paths.store_dir, paths.root)
        return {"commit_sha": sha, "diff": store.show_text(sha)}

    @app.get("/api/diff")
    def diff_between(a: int, b: int):
        conn = connect(paths.db_path)
        try:
            row_a = get_snapshot(conn, a)
            row_b = get_snapshot(conn, b)
            if row_a is None or row_b is None:
                raise HTTPException(404, "no such snapshot")
        finally:
            conn.close()
        store = ShadowStore(paths.store_dir, paths.root)
        return {"diff": store.diff_text(row_a["commit_sha"], row_b["commit_sha"])}

    @app.post("/api/snapshots/{snapshot_id}/restore")
    def restore(snapshot_id: int):
        conn = connect(paths.db_path)
        try:
            target = get_snapshot(conn, snapshot_id)
            if target is None:
                raise HTTPException(404, f"no such snapshot: {snapshot_id}")
        finally:
            conn.close()

        engine = SnapshotEngine(paths)
        safety_id = engine.capture(
            agent="chronicle",
            confidence="none",
            kind="restore-safety",
            message=f"chronicle: safety snapshot before restoring to snapshot {target['id']}",
            force=True,
        )
        engine.store.restore_worktree_to(target["commit_sha"])
        restore_id = engine.capture(
            agent="chronicle",
            confidence="none",
            kind="restore",
            restored_from_id=target["id"],
            message=f"chronicle: restored to snapshot {target['id']}",
            force=True,
        )
        return {"safety_snapshot_id": safety_id, "restore_snapshot_id": restore_id}

    @app.get("/api/blame")
    def blame(path: str, snapshot: int | None = None):
        conn = connect(paths.db_path)
        try:
            sha = None
            if snapshot is not None:
                row = get_snapshot(conn, snapshot)
                if row is None:
                    raise HTTPException(404, f"no such snapshot: {snapshot}")
                sha = row["commit_sha"]

            store = ShadowStore(paths.store_dir, paths.root)
            try:
                lines = store.blame(path, sha)
            except Exception:
                raise HTTPException(404, f"no history for {path!r}")

            result = []
            for i, (line_sha, content) in enumerate(lines, start=1):
                snap_row = get_snapshot_by_sha(conn, line_sha)
                result.append(
                    {
                        "line": i,
                        "content": content,
                        "agent": snap_row["agent"] if snap_row else None,
                        "confidence": snap_row["confidence"] if snap_row else None,
                        "snapshot_id": snap_row["id"] if snap_row else None,
                    }
                )
            return {"path": path, "lines": result}
        finally:
            conn.close()

    @app.get("/api/files")
    def files():
        conn = connect(paths.db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT path FROM file_changes ORDER BY path"
            ).fetchall()
        finally:
            conn.close()
        return [r["path"] for r in rows]

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

    return app
