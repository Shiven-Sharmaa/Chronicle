"""Repo root discovery and the fixed layout of the .chronicle/ directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CHRONICLE_DIR_NAME = ".chronicle"


class NotInitializedError(RuntimeError):
    """Raised when a command needs .chronicle/ but it doesn't exist yet."""


@dataclass(frozen=True)
class Paths:
    root: Path            # project root (where .chronicle/ lives)
    chronicle_dir: Path   # <root>/.chronicle
    store_dir: Path       # <root>/.chronicle/store   (shadow git dir)
    db_path: Path         # <root>/.chronicle/chronicle.db
    config_path: Path     # <root>/.chronicle/config.toml
    pid_path: Path        # <root>/.chronicle/daemon.pid
    log_path: Path        # <root>/.chronicle/daemon.log
    sock_path: Path       # <root>/.chronicle/daemon.sock (attribution hook endpoint, see daemon.py)
    web_port_path: Path   # <root>/.chronicle/web.port (web UI's bound TCP port, see webserver.py)

    @classmethod
    def for_root(cls, root: Path) -> "Paths":
        root = root.resolve()
        chronicle_dir = root / CHRONICLE_DIR_NAME
        return cls(
            root=root,
            chronicle_dir=chronicle_dir,
            store_dir=chronicle_dir / "store",
            db_path=chronicle_dir / "chronicle.db",
            config_path=chronicle_dir / "config.toml",
            pid_path=chronicle_dir / "daemon.pid",
            log_path=chronicle_dir / "daemon.log",
            sock_path=chronicle_dir / "daemon.sock",
            web_port_path=chronicle_dir / "web.port",
        )


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from `start` (default: cwd) looking for an existing .chronicle/.

    Falls back to the nearest .git/ directory's parent, and finally to `start`
    itself, so `chronicle init` has a sensible default location to create
    .chronicle/ in.
    """
    start = (start or Path.cwd()).resolve()
    current = start
    git_fallback: Path | None = None
    while True:
        if (current / CHRONICLE_DIR_NAME).is_dir():
            return current
        if git_fallback is None and (current / ".git").exists():
            git_fallback = current
        if current.parent == current:
            break
        current = current.parent
    return git_fallback or start


def require_paths(start: Path | None = None) -> Paths:
    """Like find_project_root, but raises if .chronicle/ doesn't actually exist."""
    root = find_project_root(start)
    paths = Paths.for_root(root)
    if not paths.chronicle_dir.is_dir():
        raise NotInitializedError(
            "No .chronicle/ found. Run `chronicle init` first."
        )
    return paths
