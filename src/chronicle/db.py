"""SQLite schema + access helpers for .chronicle/chronicle.db.

Schema follows the build plan's data model (section 4), with two small,
additive columns on `snapshots` that the plan's prose implies but the DDL
omitted:

- `kind`: distinguishes an ordinary capture from the safety snapshot and the
  restore snapshot that `chronicle restore` creates (section 8/§12 "always
  snapshot before any restore/revert"). Without it, `chronicle log` can't
  tell those apart from normal agent work.
- `restored_from_id`: for a restore snapshot, which snapshot it restored to.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id                INTEGER PRIMARY KEY,
  commit_sha        TEXT NOT NULL,
  parent_id         INTEGER REFERENCES snapshots(id),
  ts                REAL NOT NULL,
  agent             TEXT,
  session_id        TEXT,
  tool              TEXT,
  confidence        TEXT,
  kind              TEXT NOT NULL DEFAULT 'capture',
  restored_from_id  INTEGER REFERENCES snapshots(id),
  prompt_text       TEXT
);

CREATE TABLE IF NOT EXISTS file_changes (
  snapshot_id INTEGER REFERENCES snapshots(id),
  path        TEXT,
  change_type TEXT,
  added       INTEGER,
  removed     INTEGER
);

CREATE TABLE IF NOT EXISTS groups (
  id          INTEGER PRIMARY KEY,
  label       TEXT,
  prompt_text TEXT,
  agent       TEXT,
  session_id  TEXT,
  started_ts  REAL,
  ended_ts    REAL
);

CREATE TABLE IF NOT EXISTS group_members (
  group_id    INTEGER REFERENCES groups(id),
  snapshot_id INTEGER REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS test_runs (
  snapshot_id INTEGER REFERENCES snapshots(id),
  command     TEXT,
  exit_code   INTEGER,
  ts          REAL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_agent ON snapshots(agent);
CREATE INDEX IF NOT EXISTS idx_file_changes_snapshot ON file_changes(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_file_changes_path ON file_changes(path);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def last_snapshot_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    commit_sha: str,
    ts: float,
    agent: str | None,
    session_id: str | None,
    tool: str | None,
    confidence: str | None,
    kind: str = "capture",
    restored_from_id: int | None = None,
    prompt_text: str | None = None,
) -> int:
    parent_id = last_snapshot_id(conn)
    cur = conn.execute(
        """
        INSERT INTO snapshots
            (commit_sha, parent_id, ts, agent, session_id, tool, confidence,
             kind, restored_from_id, prompt_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            commit_sha,
            parent_id,
            ts,
            agent,
            session_id,
            tool,
            confidence,
            kind,
            restored_from_id,
            prompt_text,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_file_changes(
    conn: sqlite3.Connection,
    snapshot_id: int,
    changes: list[tuple[str, str, int, int]],
) -> None:
    conn.executemany(
        """
        INSERT INTO file_changes (snapshot_id, path, change_type, added, removed)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(snapshot_id, path, ct, added, removed) for path, ct, added, removed in changes],
    )
    conn.commit()


def get_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()


def get_snapshot_by_sha(conn: sqlite3.Connection, commit_sha: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM snapshots WHERE commit_sha = ?", (commit_sha,)
    ).fetchone()


def get_file_changes(conn: sqlite3.Connection, snapshot_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM file_changes WHERE snapshot_id = ? ORDER BY path",
        (snapshot_id,),
    ).fetchall()


def list_snapshots(
    conn: sqlite3.Connection,
    *,
    agent: str | None = None,
    since_ts: float | None = None,
    file: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    query = "SELECT DISTINCT s.* FROM snapshots s"
    conditions = []
    params: list = []
    if file is not None:
        query += " JOIN file_changes fc ON fc.snapshot_id = s.id"
        conditions.append("fc.path = ?")
        params.append(file)
    if agent is not None:
        conditions.append("s.agent = ?")
        params.append(agent)
    if since_ts is not None:
        conditions.append("s.ts >= ?")
        params.append(since_ts)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY s.id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()
