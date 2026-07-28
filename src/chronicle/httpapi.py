"""Minimal local HTTP endpoint served over a Unix domain socket at
.chronicle/daemon.sock.

GET /status        -- used by debugging / future UI.
POST /attribution   -- tier 1 hook adapters (e.g. Claude Code) post here.
                       Two event shapes, matching what Claude Code's hooks
                       actually send (see chronicle.hooks.claude_code):

                       {"event": "user_prompt_submit", "session_id": "...",
                        "prompt": "..."}
                       {"event": "post_tool_use", "agent": "claude-code",
                        "tool": "Edit", "session_id": "...", "ts": 1234.5}
"""

from __future__ import annotations

import json
import os
import socketserver
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from chronicle.attribution import AttributionTracker
from chronicle.db import connect


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _make_handler(paths, started_ts: float, tracker: AttributionTracker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default stderr logging
            pass

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/status":
                conn = connect(paths.db_path)
                try:
                    row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
                    count = row["n"]
                finally:
                    conn.close()
                self._json(
                    HTTPStatus.OK,
                    {
                        "pid": os.getpid(),
                        "root": str(paths.root),
                        "started_ts": started_ts,
                        "snapshot_count": count,
                    },
                )
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):
            if self.path != "/attribution":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return

            event = payload.get("event")
            if event == "user_prompt_submit":
                session_id = payload.get("session_id")
                prompt = payload.get("prompt")
                if not session_id or prompt is None:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "session_id and prompt required"})
                    return
                tracker.record_prompt(session_id, prompt)
                self._json(HTTPStatus.OK, {"ok": True})
            elif event == "post_tool_use":
                agent = payload.get("agent")
                if not agent:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "agent required"})
                    return
                tracker.record_tool_use(
                    agent=agent,
                    tool=payload.get("tool"),
                    session_id=payload.get("session_id"),
                    ts=payload.get("ts"),
                )
                self._json(HTTPStatus.OK, {"ok": True})
            else:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "unknown event"})

    return Handler


def serve(sock_path: Path, paths, started_ts: float, tracker: AttributionTracker) -> UnixHTTPServer:
    if sock_path.exists():
        sock_path.unlink()

    # AF_UNIX socket paths are capped at ~104-108 bytes by the kernel
    # (sockaddr_un.sun_path). .chronicle/ can easily live deeper than that
    # (temp dirs, CI checkouts, deeply nested project layouts), so we bind
    # using a short relative name with cwd momentarily set to its parent --
    # the resulting socket file still ends up at the correct absolute path,
    # since chdir only shortens the string handed to bind(), not where it
    # resolves to. Any future client should do the same (chdir into
    # .chronicle/ and connect to the bare "daemon.sock" name) rather than
    # connecting with the full absolute path.
    prev_cwd = os.getcwd()
    try:
        os.chdir(sock_path.parent)
        server = UnixHTTPServer(sock_path.name, _make_handler(paths, started_ts, tracker))
    finally:
        os.chdir(prev_cwd)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
