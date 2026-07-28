from __future__ import annotations

import io
import json
import time

import pytest

from chronicle import httpapi
from chronicle.attribution import AttributionTracker
from chronicle.hooks import claude_code
from chronicle.hooks.install import claude_code_hooks_installed, install_claude_code_hooks
from chronicle.paths import Paths


# ---------------------------------------------------------------------------
# settings.json installer
# ---------------------------------------------------------------------------


def test_install_writes_both_hooks(tmp_path):
    changed = install_claude_code_hooks(tmp_path)
    assert changed is True

    settings_path = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text())
    assert "PostToolUse" in data["hooks"]
    assert "UserPromptSubmit" in data["hooks"]

    post_cmd = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "chronicle.hooks.claude_code post-tool-use" in post_cmd

    prompt_cmd = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert "chronicle.hooks.claude_code user-prompt-submit" in prompt_cmd
    # UserPromptSubmit doesn't support matchers.
    assert "matcher" not in data["hooks"]["UserPromptSubmit"][0]


def test_install_is_idempotent(tmp_path):
    assert install_claude_code_hooks(tmp_path) is True
    assert install_claude_code_hooks(tmp_path) is False  # no-op second time

    settings_path = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text())
    assert len(data["hooks"]["PostToolUse"]) == 1
    assert len(data["hooks"]["UserPromptSubmit"]) == 1


def test_install_preserves_existing_hooks(tmp_path):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Edit", "hooks": [{"type": "command", "command": "/usr/local/bin/eslint"}]}
                    ]
                }
            }
        )
    )

    install_claude_code_hooks(tmp_path)

    data = json.loads(settings_path.read_text())
    commands = [
        hook["command"] for group in data["hooks"]["PostToolUse"] for hook in group["hooks"]
    ]
    assert "/usr/local/bin/eslint" in commands
    assert any("chronicle.hooks.claude_code" in cmd for cmd in commands)


def test_hooks_status_reflects_installation(tmp_path):
    assert claude_code_hooks_installed(tmp_path) is False
    install_claude_code_hooks(tmp_path)
    assert claude_code_hooks_installed(tmp_path) is True


# ---------------------------------------------------------------------------
# the hook script itself, against a real (in-process) daemon HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def live_server(initialized: Paths):
    tracker = AttributionTracker(window_s=3.0)
    server = httpapi.serve(initialized.sock_path, initialized, time.time(), tracker)
    yield tracker
    server.shutdown()
    server.server_close()


def test_post_tool_use_hook_reaches_tracker(initialized: Paths, live_server, monkeypatch):
    tracker = live_server
    payload = {
        "session_id": "sess-1",
        "cwd": str(initialized.root),
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    rc = claude_code.main(["post-tool-use"])
    assert rc == 0

    attrib = tracker.take()
    assert attrib is not None
    assert attrib.agent == "claude-code"
    assert attrib.tool == "Edit"
    assert attrib.session_id == "sess-1"


def test_user_prompt_submit_hook_is_inherited_by_next_tool_use(initialized: Paths, live_server, monkeypatch):
    tracker = live_server

    prompt_payload = {
        "session_id": "sess-2",
        "cwd": str(initialized.root),
        "hook_event_name": "UserPromptSubmit",
        "user_message": "refactor the auth module",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(prompt_payload)))
    assert claude_code.main(["user-prompt-submit"]) == 0

    tool_payload = {
        "session_id": "sess-2",
        "cwd": str(initialized.root),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(tool_payload)))
    assert claude_code.main(["post-tool-use"]) == 0

    attrib = tracker.take()
    assert attrib.prompt_text == "refactor the auth module"
    assert attrib.tool == "Bash"


def test_hook_is_a_noop_when_chronicle_not_initialized(tmp_path, monkeypatch):
    payload = {"session_id": "s", "cwd": str(tmp_path), "tool_name": "Edit"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    # No .chronicle/ at all here -- must not raise.
    assert claude_code.main(["post-tool-use"]) == 0
