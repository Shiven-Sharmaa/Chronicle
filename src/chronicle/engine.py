"""SnapshotEngine: the one place that turns "working tree changed" into a
recorded snapshot -- used by `chronicle init` (first snapshot), the watcher
(ongoing captures), and `restore` (safety + restore snapshots).

Phase 1 attribution is intentionally a stub: every capture is recorded as
agent='unknown', confidence='none'. Tiers 1-3 (hooks, process wrapper,
process inspection) are phase 2 -- the schema and CLI already have the
columns/filters for it so nothing here needs to change shape later.
"""

from __future__ import annotations

import time

from chronicle.db import connect, insert_file_changes, insert_snapshot
from chronicle.paths import Paths
from chronicle.store import ShadowStore


class SnapshotEngine:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.store = ShadowStore(paths.store_dir, paths.root)

    def capture(
        self,
        *,
        agent: str | None = "unknown",
        session_id: str | None = None,
        tool: str | None = None,
        confidence: str | None = "none",
        kind: str = "capture",
        restored_from_id: int | None = None,
        prompt_text: str | None = None,
        message: str | None = None,
        force: bool = False,
    ) -> int | None:
        """Stage + commit the working tree as a new snapshot, record it in
        sqlite, and pin it with a ref. Returns the new snapshot id, or None
        if nothing changed and force=False (no wasted empty commits from
        watcher noise)."""
        self.store.stage_all()
        if not force and not self.store.has_staged_changes():
            self.store.git.run(["reset", "--quiet"])
            return None

        msg = message or f"snapshot @ {time.time():.3f}"
        sha = self.store.commit_staged(msg)
        parent_sha = self.store.parent_sha(sha)

        conn = connect(self.paths.db_path)
        try:
            snap_id = insert_snapshot(
                conn,
                commit_sha=sha,
                ts=time.time(),
                agent=agent,
                session_id=session_id,
                tool=tool,
                confidence=confidence,
                kind=kind,
                restored_from_id=restored_from_id,
                prompt_text=prompt_text,
            )
            changes = self.store.name_status(parent_sha, sha)
            stats = self.store.numstat(parent_sha, sha)
            rows = [
                (path, change_type, *stats.get(path, (0, 0)))
                for change_type, path in changes
            ]
            if rows:
                insert_file_changes(conn, snap_id, rows)
        finally:
            conn.close()

        self.store.create_ref(snap_id, sha)
        return snap_id
