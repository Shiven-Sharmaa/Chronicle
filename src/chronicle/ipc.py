"""Tiny client for the daemon's Unix-socket HTTP endpoint.

Mirrors the chdir-relative-bind trick in httpapi.serve(): AF_UNIX paths are
capped at ~104-108 bytes, so we connect using a short relative name with cwd
momentarily set to .chronicle/, rather than the full absolute socket path.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


class DaemonUnavailable(Exception):
    pass


def post(chronicle_dir: Path, path: str, payload: dict, timeout: float = 1.0) -> dict | None:
    sock_path = chronicle_dir / "daemon.sock"
    if not sock_path.exists():
        raise DaemonUnavailable("daemon.sock not found -- is the daemon running?")

    body = json.dumps(payload).encode()
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    prev_cwd = os.getcwd()
    try:
        os.chdir(chronicle_dir)
        try:
            sock.connect("daemon.sock")
        finally:
            os.chdir(prev_cwd)

        sock.sendall(request)
        response = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        except TimeoutError:
            pass
    finally:
        sock.close()

    if b"\r\n\r\n" not in response:
        return None
    _, _, body_bytes = response.partition(b"\r\n\r\n")
    try:
        return json.loads(body_bytes)
    except json.JSONDecodeError:
        return None
