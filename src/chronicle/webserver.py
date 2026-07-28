"""Runs the web UI's FastAPI app (over plain TCP, since a browser can't
reach a Unix socket) inside the daemon process, in its own thread.

Port selection: probe for a free port by binding a throwaway socket and
closing it, then hand that port to uvicorn's normal host/port bind path.

This used to instead keep the probe socket open and pass its fd to uvicorn
via `Config(fd=...)`, meant to avoid the probe-then-bind race entirely. That
turned out to be broken: uvicorn's fd code path is hardcoded to
`socket.fromfd(fd, socket.AF_UNIX, ...)` in this version regardless of the
socket's real family, so a pre-bound AF_INET fd fails with "Socket operation
on non-socket" the moment the server starts -- confirmed by actually running
it, not just reading the uvicorn source. Reverted to the well-supported
host/port path; the small TOCTOU window between probe and bind is an
acceptable tradeoff for a single-user local tool. Startup is verified by
actually connecting before reporting success, so a lost race surfaces as a
clear failure instead of a silently-dead server.
"""

from __future__ import annotations

import socket
import threading
import time

import uvicorn

from chronicle.paths import Paths
from chronicle.webapp import create_app

PORT_SEARCH_RANGE = 50
STARTUP_TIMEOUT_S = 5.0


class WebServerHandle:
    def __init__(self, server: uvicorn.Server, thread: threading.Thread, port: int):
        self.server = server
        self.thread = thread
        self.port = port

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _probe_free_port(start_port: int) -> int:
    last_error: OSError | None = None
    for port in range(start_port, start_port + PORT_SEARCH_RANGE):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return port
        except OSError as e:
            last_error = e
        finally:
            sock.close()
    raise RuntimeError(
        f"could not find a free port in [{start_port}, {start_port + PORT_SEARCH_RANGE})"
    ) from last_error


def _wait_until_accepting(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.05)
    return False


def start(paths: Paths, preferred_port: int) -> WebServerHandle:
    port = _probe_free_port(preferred_port)

    app = create_app(paths)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_until_accepting(port, STARTUP_TIMEOUT_S):
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError(f"web UI server did not come up on port {port} in time")

    paths.chronicle_dir.mkdir(parents=True, exist_ok=True)
    paths.web_port_path.write_text(str(port))

    return WebServerHandle(server, thread, port)
