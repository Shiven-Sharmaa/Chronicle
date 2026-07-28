"""Filesystem watcher + debouncer.

A burst of file events collapses into a single snapshot: we flush after
`debounce_ms` of quiet, or after `max_batch_window_s` regardless (so a
long-running build that writes files continuously for 30s doesn't delay
capture indefinitely).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from chronicle import attribution
from chronicle.attribution import AttributionTracker
from chronicle.config import Config
from chronicle.engine import SnapshotEngine
from chronicle.ignore import is_statically_excluded
from chronicle.paths import Paths

logger = logging.getLogger("chronicle.watcher")

POLL_INTERVAL_S = 0.1


class _DebouncedFlusher:
    def __init__(self, paths: Paths, engine: SnapshotEngine, config: Config, tracker: AttributionTracker):
        self.paths = paths
        self.engine = engine
        self.tracker = tracker
        self.debounce_s = config.debounce_ms / 1000.0
        self.max_batch_window_s = config.max_batch_window_s
        self._lock = threading.Lock()
        self._first_event_ts: float | None = None
        self._last_event_ts: float | None = None
        self._dirty = False

    def notify(self) -> None:
        with self._lock:
            now = time.time()
            if self._first_event_ts is None:
                self._first_event_ts = now
            self._last_event_ts = now
            self._dirty = True

    def _should_flush_locked(self) -> bool:
        if not self._dirty:
            return False
        now = time.time()
        quiet_elapsed = now - self._last_event_ts
        total_elapsed = now - self._first_event_ts
        return quiet_elapsed >= self.debounce_s or total_elapsed >= self.max_batch_window_s

    def _flush_if_due(self) -> None:
        with self._lock:
            due = self._should_flush_locked()
            if due:
                self._dirty = False
                self._first_event_ts = None
                self._last_event_ts = None
        if due:
            self._do_flush()

    def _do_flush(self) -> None:
        try:
            attrib = attribution.resolve(self.paths, self.tracker)
            snap_id = self.engine.capture(**attrib.as_kwargs())
            if snap_id is not None:
                logger.info(
                    "captured snapshot %s (agent=%s confidence=%s)",
                    snap_id, attrib.agent, attrib.confidence,
                )
        except Exception:
            logger.exception("snapshot capture failed")

    def flush_pending(self) -> None:
        with self._lock:
            dirty = self._dirty
            self._dirty = False
            self._first_event_ts = None
            self._last_event_ts = None
        if dirty:
            self._do_flush()

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            stop_event.wait(POLL_INTERVAL_S)
            self._flush_if_due()
        self.flush_pending()


class _Handler(FileSystemEventHandler):
    def __init__(self, paths: Paths, excludes: list[str], flusher: _DebouncedFlusher):
        self.paths = paths
        self.excludes = excludes
        self.flusher = flusher

    def _relevant(self, path: str) -> bool:
        try:
            rel = Path(path).resolve().relative_to(self.paths.root)
        except ValueError:
            return False
        if str(rel) == ".":
            return False
        return not is_statically_excluded(str(rel), self.excludes)

    def on_any_event(self, event) -> None:
        paths_to_check = [event.src_path]
        dest = getattr(event, "dest_path", None)
        if dest:
            paths_to_check.append(dest)
        if any(self._relevant(p) for p in paths_to_check):
            self.flusher.notify()


class Watcher:
    """Owns the watchdog Observer + debounce thread. Call start()/stop()."""

    def __init__(self, paths: Paths, config: Config, tracker: AttributionTracker | None = None):
        self.paths = paths
        self.config = config
        self.engine = SnapshotEngine(paths)
        # A caller that also runs the HTTP endpoint (the daemon) passes in a
        # shared tracker so hook POSTs reach this flusher. Standalone use
        # (tests, no HTTP server) gets its own tracker, which simply never
        # receives tier-1 hook events -- tiers 2/3/fallback still work.
        self.tracker = tracker or AttributionTracker(config.attribution_window_s)
        self.flusher = _DebouncedFlusher(self.paths, self.engine, config, self.tracker)
        self._stop_event = threading.Event()
        self._debounce_thread: threading.Thread | None = None
        self._observer: Observer | None = None

    def start(self) -> None:
        handler = _Handler(self.paths, self.config.excludes, self.flusher)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.paths.root), recursive=True)
        self._observer.start()

        self._debounce_thread = threading.Thread(
            target=self.flusher.run, args=(self._stop_event,), daemon=True
        )
        self._debounce_thread.start()
        logger.info("watching %s", self.paths.root)

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        if self._debounce_thread is not None:
            self._debounce_thread.join(timeout=self.config.max_batch_window_s + 2)

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
