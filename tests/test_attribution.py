from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from chronicle import attribution
from chronicle.attribution import AttributionTracker
from chronicle.paths import Paths


# ---------------------------------------------------------------------------
# Tier 1: hook tracker
# ---------------------------------------------------------------------------


def test_tracker_take_returns_none_when_empty():
    tracker = AttributionTracker(window_s=3.0)
    assert tracker.take() is None


def test_tracker_take_returns_hook_context():
    tracker = AttributionTracker(window_s=3.0)
    tracker.record_prompt("sess-1", "add rate limiting")
    tracker.record_tool_use(agent="claude-code", tool="Edit", session_id="sess-1")

    attrib = tracker.take()
    assert attrib is not None
    assert attrib.agent == "claude-code"
    assert attrib.tool == "Edit"
    assert attrib.session_id == "sess-1"
    assert attrib.confidence == "hook"
    assert attrib.prompt_text == "add rate limiting"


def test_tracker_take_consumes_context_once():
    tracker = AttributionTracker(window_s=3.0)
    tracker.record_tool_use(agent="claude-code", tool="Edit", session_id="s")
    assert tracker.take() is not None
    assert tracker.take() is None  # second flush in the same window gets nothing


def test_tracker_take_expires_after_window():
    tracker = AttributionTracker(window_s=0.1)
    tracker.record_tool_use(agent="claude-code", tool="Bash", session_id="s")
    time.sleep(0.2)
    assert tracker.take() is None


def test_tracker_without_prompt_has_no_prompt_text():
    tracker = AttributionTracker(window_s=3.0)
    tracker.record_tool_use(agent="claude-code", tool="Bash", session_id="unseen-session")
    attrib = tracker.take()
    assert attrib.prompt_text is None


# ---------------------------------------------------------------------------
# Tier 2: process wrapper marker files
# ---------------------------------------------------------------------------


def test_resolve_wrapper_none_when_no_markers(initialized: Paths):
    assert attribution.resolve_wrapper(initialized.chronicle_dir) is None


def test_resolve_wrapper_single_active_marker(initialized: Paths):
    marker = attribution.register_wrapper(
        initialized.chronicle_dir, pid=1, agent="codex", session_id="s1"
    )
    # pid=1 (init/launchd) always exists on both Linux and macOS.
    attrib = attribution.resolve_wrapper(initialized.chronicle_dir)
    assert attrib is not None
    assert attrib.agent == "codex"
    assert attrib.confidence == "wrapper"
    attribution.unregister_wrapper(marker)


def test_resolve_wrapper_ambiguous_with_two_active_markers(initialized: Paths):
    # Two distinct live processes standing in for two concurrently-wrapped
    # agents -- resolve_wrapper must refuse to guess between them.
    p1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    p2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    m1 = attribution.register_wrapper(initialized.chronicle_dir, pid=p1.pid, agent="codex", session_id="s1")
    m2 = attribution.register_wrapper(
        initialized.chronicle_dir, pid=p2.pid, agent="claude-code", session_id="s2"
    )
    try:
        assert attribution.resolve_wrapper(initialized.chronicle_dir) is None
    finally:
        attribution.unregister_wrapper(m1)
        attribution.unregister_wrapper(m2)
        p1.terminate()
        p2.terminate()
        p1.wait(timeout=5)
        p2.wait(timeout=5)


def test_resolve_wrapper_cleans_up_stale_marker(initialized: Paths):
    # A pid that (almost certainly) doesn't exist.
    dead_pid = 999999
    attribution.register_wrapper(initialized.chronicle_dir, pid=dead_pid, agent="codex", session_id="s1")
    assert attribution.resolve_wrapper(initialized.chronicle_dir) is None
    marker = attribution.wrappers_dir(initialized.chronicle_dir) / f"{dead_pid}.json"
    assert not marker.exists()  # self-healed


# ---------------------------------------------------------------------------
# Tier 3: process inspection
# ---------------------------------------------------------------------------


def _spawn_fake_agent(cwd: Path, name: str) -> subprocess.Popen:
    """Exec a shebang script literally named `name` (e.g. "codex"), so its
    argv looks like a real agent CLI invocation: ['/bin/sh', '<path>/name'].
    This is what detect_running_agents actually matches against -- not an
    arbitrary substring buried somewhere in a long argument list."""
    script = cwd / name
    script.write_text("#!/bin/sh\nsleep 5\n")
    script.chmod(0o755)
    return subprocess.Popen([str(script)], cwd=cwd)


def _wait_for(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_detect_running_agents_finds_known_process(tmp_path: Path):
    proc = _spawn_fake_agent(tmp_path, "codex")
    try:
        assert _wait_for(lambda: attribution.detect_running_agents(tmp_path) == {"codex"})
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_detect_running_agents_empty_when_none_match(tmp_path: Path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"], cwd=tmp_path)
    try:
        time.sleep(0.3)
        assert attribution.detect_running_agents(tmp_path) == set()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_detect_running_agents_finds_multiple(tmp_path: Path):
    p1 = _spawn_fake_agent(tmp_path, "codex")
    p2 = _spawn_fake_agent(tmp_path, "claude")
    try:
        assert _wait_for(
            lambda: attribution.detect_running_agents(tmp_path) == {"codex", "claude-code"}
        )
    finally:
        p1.terminate()
        p2.terminate()
        p1.wait(timeout=5)
        p2.wait(timeout=5)


# ---------------------------------------------------------------------------
# Combined resolution + priority ordering
# ---------------------------------------------------------------------------


def test_resolve_prefers_hook_over_wrapper(initialized: Paths):
    tracker = AttributionTracker(window_s=3.0)
    tracker.record_tool_use(agent="claude-code", tool="Edit", session_id="s1")
    marker = attribution.register_wrapper(initialized.chronicle_dir, pid=1, agent="codex", session_id="s2")
    try:
        attrib = attribution.resolve(initialized, tracker)
        assert attrib.agent == "claude-code"
        assert attrib.confidence == "hook"
    finally:
        attribution.unregister_wrapper(marker)


def test_resolve_falls_back_to_wrapper_without_hook(initialized: Paths):
    tracker = AttributionTracker(window_s=3.0)
    marker = attribution.register_wrapper(initialized.chronicle_dir, pid=1, agent="codex", session_id="s1")
    try:
        attrib = attribution.resolve(initialized, tracker)
        assert attrib.agent == "codex"
        assert attrib.confidence == "wrapper"
    finally:
        attribution.unregister_wrapper(marker)


def test_resolve_falls_back_to_human_when_nothing_detected(initialized: Paths):
    tracker = AttributionTracker(window_s=3.0)
    attrib = attribution.resolve(initialized, tracker)
    assert attrib.agent == "human"
    assert attrib.confidence == "none"
