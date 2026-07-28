"""Writes/merges Claude Code hook registrations into .claude/settings.json.

Idempotent: running it twice (or running `chronicle init` twice) doesn't
duplicate entries, and existing hooks the user already has configured for
other tools are preserved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_MARKER = "chronicle.hooks.claude_code"


def _hook_command(event: str) -> str:
    return f"{sys.executable} -m chronicle.hooks.claude_code {event}"


def _already_installed(groups: list[dict]) -> bool:
    for group in groups:
        for hook in group.get("hooks", []):
            if _MARKER in hook.get("command", ""):
                return True
    return False


def install_claude_code_hooks(root: Path) -> bool:
    """Merge chronicle's hooks into .claude/settings.json. Returns True if
    it changed anything, False if already installed."""
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    hooks = data.setdefault("hooks", {})
    post_tool_use = hooks.setdefault("PostToolUse", [])
    user_prompt_submit = hooks.setdefault("UserPromptSubmit", [])

    changed = False
    if not _already_installed(post_tool_use):
        post_tool_use.append(
            {
                "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
                "hooks": [
                    {"type": "command", "command": _hook_command("post-tool-use"), "timeout": 10}
                ],
            }
        )
        changed = True

    if not _already_installed(user_prompt_submit):
        # UserPromptSubmit doesn't support matchers -- it always fires.
        user_prompt_submit.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": _hook_command("user-prompt-submit"),
                        "timeout": 10,
                    }
                ]
            }
        )
        changed = True

    if changed:
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
    return changed


def claude_code_hooks_installed(root: Path) -> bool:
    settings_path = root / ".claude" / "settings.json"
    if not settings_path.exists():
        return False
    data = json.loads(settings_path.read_text())
    hooks = data.get("hooks", {})
    return _already_installed(hooks.get("PostToolUse", [])) and _already_installed(
        hooks.get("UserPromptSubmit", [])
    )
