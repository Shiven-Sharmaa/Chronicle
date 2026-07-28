"""The three attribution tiers (build plan section 6), highest confidence first:

  1. hooks     -- a tool adapter (e.g. Claude Code) told us directly, in real
                  time, which agent/tool/session did this. Confidence: 'hook'.
  2. wrapper   -- the change happened while exactly one `chronicle run
                  --agent X -- cmd` child process was alive. Confidence:
                  'wrapper'.
  3. process   -- no direct signal, but exactly one known agent CLI process
                  has this repo as its cwd. Confidence: 'process'. This is a
                  guess and must never be displayed as if it were tier 1/2.

If none of those resolve, we fall back to 'human' (nothing agent-like is
running -- most likely a person editing directly) or 'unknown' (more than
one candidate and we can't tell which), both with confidence=None.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

# Substrings matched against a running process's name + cmdline (lowercased).
# Order doesn't matter; first match wins per process. Deliberately narrow --
# false positives are exactly why this tier is low-confidence.
KNOWN_AGENT_PROCESSES: dict[str, str] = {
    "claude": "claude-code",
    "codex": "codex",
    "cursor-agent": "cursor",
}


@dataclass(frozen=True)
class Attribution:
    agent: str | None
    tool: str | None
    session_id: str | None
    confidence: str | None
    prompt_text: str | None = None

    def as_kwargs(self) -> dict:
        return {
            "agent": self.agent,
            "tool": self.tool,
            "session_id": self.session_id,
            "confidence": self.confidence,
            "prompt_text": self.prompt_text,
        }


@dataclass
class _HookContext:
    agent: str
    tool: str | None
    session_id: str | None
    prompt: str | None
    ts: float


class AttributionTracker:
    """Tier 1 state: the daemon's in-memory record of the most recent hook
    events, shared between the HTTP handler thread (which receives POSTs)
    and the watcher's flush thread (which consumes it)."""

    def __init__(self, window_s: float):
        self.window_s = window_s
        self._lock = threading.Lock()
        self._context: _HookContext | None = None
        self._prompts: dict[str, str] = {}  # session_id -> last user_message

    def record_prompt(self, session_id: str, prompt: str) -> None:
        with self._lock:
            self._prompts[session_id] = prompt

    def record_tool_use(
        self,
        *,
        agent: str,
        tool: str | None,
        session_id: str | None,
        ts: float | None = None,
    ) -> None:
        with self._lock:
            prompt = self._prompts.get(session_id) if session_id else None
            self._context = _HookContext(
                agent=agent, tool=tool, session_id=session_id, prompt=prompt, ts=ts or time.time()
            )

    def take(self) -> Attribution | None:
        """Return and clear the active hook context, if still within its
        window. Each hook event is consumed by at most one snapshot flush."""
        with self._lock:
            ctx = self._context
            if ctx is None:
                return None
            self._context = None
            if time.time() - ctx.ts > self.window_s:
                return None
            return Attribution(
                agent=ctx.agent,
                tool=ctx.tool,
                session_id=ctx.session_id,
                confidence="hook",
                prompt_text=ctx.prompt,
            )


# ---------------------------------------------------------------------------
# Tier 2: process wrapper marker files
# ---------------------------------------------------------------------------


def wrappers_dir(chronicle_dir: Path) -> Path:
    return chronicle_dir / "wrappers"


def register_wrapper(chronicle_dir: Path, pid: int, agent: str, session_id: str) -> Path:
    d = wrappers_dir(chronicle_dir)
    d.mkdir(parents=True, exist_ok=True)
    marker = d / f"{pid}.json"
    marker.write_text(json.dumps({"pid": pid, "agent": agent, "session_id": session_id, "started_ts": time.time()}))
    return marker


def unregister_wrapper(marker: Path) -> None:
    marker.unlink(missing_ok=True)


def _active_wrappers(chronicle_dir: Path) -> list[dict]:
    d = wrappers_dir(chronicle_dir)
    if not d.is_dir():
        return []
    live = []
    for marker in d.glob("*.json"):
        try:
            data = json.loads(marker.read_text())
        except (OSError, json.JSONDecodeError):
            marker.unlink(missing_ok=True)
            continue
        if psutil.pid_exists(data.get("pid", -1)):
            live.append(data)
        else:
            marker.unlink(missing_ok=True)  # stale -- process died without cleanup
    return live


def resolve_wrapper(chronicle_dir: Path) -> Attribution | None:
    live = _active_wrappers(chronicle_dir)
    if len(live) == 1:
        w = live[0]
        return Attribution(
            agent=w["agent"], tool=None, session_id=w.get("session_id"), confidence="wrapper"
        )
    return None  # zero or several -- ambiguous, fall through


# ---------------------------------------------------------------------------
# Tier 3: process inspection
# ---------------------------------------------------------------------------


def detect_running_agents(root: Path) -> set[str]:
    """The set of known agent CLI processes that have `root` as their cwd.
    Zero means no agent-like process is running here; more than one means
    we can see agent activity but can't tell which one made this change.

    Only the executable name and its first argument are checked (e.g.
    `claude`, or `node /path/to/codex/cli.js`) -- NOT the full cmdline.
    Matching the whole cmdline text is a real trap: a shell process running
    a chronicle command itself (or anything else) can carry long, unrelated
    argument strings -- e.g. a wrapper shell that sources a path under
    `~/.claude/...` -- that spuriously contain a needle like "claude"
    somewhere deep inside them. Restricting to argv[0]/argv[1] avoids that
    class of false positive while still catching real invocations."""
    root_resolved = root.resolve()
    matches: set[str] = set()
    for proc in psutil.process_iter(["pid", "name", "cwd", "cmdline"]):
        try:
            cwd = proc.info.get("cwd")
            if not cwd or Path(cwd).resolve() != root_resolved:
                continue
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            argv0 = Path(cmdline[0]).name.lower() if cmdline else ""
            argv1 = Path(cmdline[1]).name.lower() if len(cmdline) > 1 else ""
            haystack = f"{name} {argv0} {argv1}"
            for needle, agent in KNOWN_AGENT_PROCESSES.items():
                if needle in haystack:
                    matches.add(agent)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return matches


# ---------------------------------------------------------------------------
# Combined resolution
# ---------------------------------------------------------------------------


def resolve(paths, tracker: AttributionTracker | None) -> Attribution:
    if tracker is not None:
        hook = tracker.take()
        if hook is not None:
            return hook

    wrapper = resolve_wrapper(paths.chronicle_dir)
    if wrapper is not None:
        return wrapper

    candidates = detect_running_agents(paths.root)
    if len(candidates) == 1:
        return Attribution(agent=next(iter(candidates)), tool=None, session_id=None, confidence="process")
    if len(candidates) == 0:
        # Nothing agent-like running against this repo -- most likely a
        # human editing directly.
        return Attribution(agent="human", tool=None, session_id=None, confidence="none")
    # Several candidates running concurrently and no hook/wrapper claimed
    # this snapshot -- we genuinely can't tell which one did it.
    return Attribution(agent="unknown", tool=None, session_id=None, confidence="none")
