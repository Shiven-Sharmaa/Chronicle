"""Daemon process lifecycle: start/stop/status, plus the foreground entry
point that actually runs the watcher + HTTP endpoint.

`chronicle daemon start` launches a detached child process
(`python -m chronicle.daemon --foreground <root>`) so it survives the
terminal closing, and confirms it came up by polling for the pid file it
writes on startup.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from chronicle import webserver
from chronicle.attribution import AttributionTracker
from chronicle.config import Config
from chronicle.httpapi import serve
from chronicle.paths import Paths
from chronicle.watcher import Watcher


def is_running(paths: Paths) -> int | None:
    """Return the daemon's pid if alive, else None (cleaning up a stale pid file)."""
    if not paths.pid_path.exists():
        return None
    try:
        pid = int(paths.pid_path.read_text().strip())
    except (ValueError, OSError):
        return None
    if psutil.pid_exists(pid):
        return pid
    paths.pid_path.unlink(missing_ok=True)
    return None


def start(paths: Paths) -> int:
    existing = is_running(paths)
    if existing is not None:
        raise RuntimeError(f"daemon already running (pid {existing})")

    paths.chronicle_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(paths.log_path, "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "chronicle.daemon", "--foreground", str(paths.root)],
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        cwd=paths.root,
        start_new_session=True,
    )
    deadline = time.time() + 3.0
    while time.time() < deadline:
        pid = is_running(paths)
        if pid is not None:
            return pid
        if proc.poll() is not None:
            raise RuntimeError(
                f"daemon exited immediately (code {proc.returncode}); see {paths.log_path}"
            )
        time.sleep(0.05)
    raise RuntimeError(f"daemon did not start in time; see {paths.log_path}")


def stop(paths: Paths) -> bool:
    pid = is_running(paths)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline and psutil.pid_exists(pid):
        time.sleep(0.05)
    paths.pid_path.unlink(missing_ok=True)
    return True


def _run_foreground(paths: Paths) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load(paths.config_path)
    paths.pid_path.write_text(str(os.getpid()))

    # Shared between the watcher's flush thread (consumes hook context) and
    # the HTTP handler threads (receive hook POSTs from e.g. Claude Code).
    tracker = AttributionTracker(config.attribution_window_s)

    watcher = Watcher(paths, config, tracker=tracker)
    watcher.start()

    http_server = None
    try:
        http_server = serve(paths.sock_path, paths, time.time(), tracker)
    except OSError:
        logging.getLogger("chronicle.daemon").warning(
            "could not bind daemon.sock; continuing without the local HTTP "
            "endpoint (watcher/snapshots are unaffected)",
            exc_info=True,
        )

    web_handle = None
    try:
        web_handle = webserver.start(paths, config.ui_port)
        logging.getLogger("chronicle.daemon").info(
            "web UI on http://127.0.0.1:%s", web_handle.port
        )
    except Exception:
        logging.getLogger("chronicle.daemon").warning(
            "could not start the web UI server; `chronicle ui` will be "
            "unavailable (watcher/snapshots are unaffected)",
            exc_info=True,
        )

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        stop_event.wait()
    finally:
        watcher.stop()
        if http_server is not None:
            http_server.shutdown()
        if web_handle is not None:
            web_handle.stop()
        paths.pid_path.unlink(missing_ok=True)
        for p in (paths.sock_path, paths.web_port_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--foreground":
        root = Path(sys.argv[2])
        paths = Paths.for_root(root)
        sys.exit(_run_foreground(paths))
    else:
        print("usage: python -m chronicle.daemon --foreground <root>", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
