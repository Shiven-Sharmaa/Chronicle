"""Claude Code hook adapter (tier 1 attribution).

Registered into .claude/settings.json by `chronicle.hooks.install`,
invoked by Claude Code itself for PostToolUse and UserPromptSubmit. Must
never block or fail Claude Code's turn -- every error here is swallowed and
we always exit 0, since chronicle is a passive observer, not part of the
agent's control flow.

Payload shapes (verified against https://code.claude.com/docs/en/hooks on
2026-07-29 -- re-check if this stops matching):

  PostToolUse stdin:      {"session_id", "tool_name", "cwd", "tool_input", ...}
                          (no prompt text -- only UserPromptSubmit has that)
  UserPromptSubmit stdin: {"session_id", "user_message", "cwd", ...}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from chronicle import ipc
from chronicle.paths import Paths, find_project_root


def _resolve_paths(payload: dict) -> Paths | None:
    cwd = payload.get("cwd")
    root = find_project_root(Path(cwd) if cwd else None)
    paths = Paths.for_root(root)
    if not paths.chronicle_dir.is_dir():
        return None
    return paths


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        return 0
    event = argv[0]

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return 0

    try:
        paths = _resolve_paths(payload)
        if paths is None:
            return 0

        if event == "post-tool-use":
            ipc.post(
                paths.chronicle_dir,
                "/attribution",
                {
                    "event": "post_tool_use",
                    "agent": "claude-code",
                    "tool": payload.get("tool_name"),
                    "session_id": payload.get("session_id"),
                    "ts": time.time(),
                },
            )
        elif event == "user-prompt-submit":
            ipc.post(
                paths.chronicle_dir,
                "/attribution",
                {
                    "event": "user_prompt_submit",
                    "session_id": payload.get("session_id"),
                    "prompt": payload.get("user_message"),
                },
            )
    except Exception:
        pass  # never block or fail the user's Claude Code session

    return 0


if __name__ == "__main__":
    sys.exit(main())
