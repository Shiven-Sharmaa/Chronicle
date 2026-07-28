from __future__ import annotations

import argparse
import re
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from chronicle import daemon as daemon_mod
from chronicle import run_wrapper
from chronicle.config import Config
from chronicle.db import (
    connect,
    get_file_changes,
    get_snapshot,
    get_snapshot_by_sha,
    init_db,
    list_snapshots,
)
from chronicle.engine import SnapshotEngine
from chronicle.hooks.install import claude_code_hooks_installed, install_claude_code_hooks
from chronicle.paths import NotInitializedError, Paths, require_paths
from chronicle.store import ShadowStore

_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_since(text: str) -> float:
    m = _DURATION_RE.match(text.strip())
    if not m:
        raise SystemExit(
            f"invalid --since value {text!r}; expected e.g. 30m, 2h, 3d, 1w"
        )
    n, unit = m.groups()
    return time.time() - int(n) * _DURATION_SECONDS[unit]


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _snapshot_or_die(conn, snap_id: int):
    row = get_snapshot(conn, snap_id)
    if row is None:
        raise SystemExit(f"no such snapshot: {snap_id}")
    return row


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    root = Path(args.path).resolve() if args.path else Path.cwd()
    paths = Paths.for_root(root)

    if paths.chronicle_dir.exists():
        print(f"chronicle already initialized at {paths.chronicle_dir}")
        return

    paths.chronicle_dir.mkdir(parents=True)
    config = Config()
    config.save(paths.config_path)

    store = ShadowStore(paths.store_dir, paths.root)
    store.init(config.excludes)

    init_db(paths.db_path)

    engine = SnapshotEngine(paths)
    snap_id = engine.capture(
        agent="chronicle",
        confidence="none",
        kind="capture",
        message="chronicle: initial snapshot",
        force=True,
    )

    print(f"Initialized chronicle in {paths.chronicle_dir}")
    print(f"Baseline snapshot recorded (id {snap_id}).")
    print()

    want_hooks = args.hooks
    if want_hooks is None:
        if sys.stdin.isatty():
            resp = input("Install Claude Code attribution hooks now? [Y/n] ")
            want_hooks = resp.strip().lower() in ("", "y", "yes")
        else:
            want_hooks = False

    if want_hooks:
        install_claude_code_hooks(paths.root)
        print(f"Installed Claude Code hooks in {paths.root / '.claude' / 'settings.json'}")
    else:
        print(
            "Run `chronicle hooks install claude-code` any time to enable "
            "per-tool attribution for Claude Code."
        )
    print()
    print("Next steps:")
    print("  chronicle daemon start          # begin watching this project")
    print("  chronicle run --agent codex -- codex   # attribute a hook-less tool")
    print("  chronicle log                   # see recorded snapshots")


def cmd_daemon_start(args: argparse.Namespace) -> None:
    paths = require_paths()
    try:
        pid = daemon_mod.start(paths)
    except RuntimeError as e:
        raise SystemExit(str(e))
    print(f"daemon started (pid {pid}), watching {paths.root}")


def cmd_daemon_stop(args: argparse.Namespace) -> None:
    paths = require_paths()
    if daemon_mod.stop(paths):
        print("daemon stopped")
    else:
        print("daemon is not running")


def cmd_daemon_status(args: argparse.Namespace) -> None:
    paths = require_paths()
    pid = daemon_mod.is_running(paths)
    if pid is None:
        print("daemon is not running")
    else:
        print(f"daemon is running (pid {pid})")


def cmd_ui(args: argparse.Namespace) -> None:
    paths = require_paths()
    if daemon_mod.is_running(paths) is None:
        print("Starting daemon...")
        daemon_mod.start(paths)

    deadline = time.time() + 10.0
    while time.time() < deadline and not paths.web_port_path.exists():
        time.sleep(0.05)
    if not paths.web_port_path.exists():
        raise SystemExit(
            f"web UI did not start in time; check {paths.log_path}"
        )

    port = paths.web_port_path.read_text().strip()
    url = f"http://127.0.0.1:{port}/"
    print(f"Opening {url}")
    if not args.no_browser:
        webbrowser.open(url)


def cmd_log(args: argparse.Namespace) -> None:
    paths = require_paths()
    conn = connect(paths.db_path)
    try:
        since_ts = _parse_since(args.since) if args.since else None
        rows = list_snapshots(
            conn, agent=args.agent, since_ts=since_ts, file=args.file, limit=args.limit
        )
        if not rows:
            print("No changes recorded yet. Start your agent and they'll appear here.")
            return
        for row in rows:
            changes = get_file_changes(conn, row["id"])
            added = sum(c["added"] or 0 for c in changes)
            removed = sum(c["removed"] or 0 for c in changes)
            label = row["prompt_text"] or (
                f"{len(changes)} file(s)" if changes else "no file changes"
            )
            conf = row["confidence"] or "none"
            print(
                f"[{row['id']:>5}] {_fmt_ts(row['ts'])}  "
                f"{row['agent'] or 'unknown':<12} ({conf:<6})  "
                f"{row['kind']:<8}  +{added}/-{removed}  {label}"
            )
    finally:
        conn.close()


def cmd_show(args: argparse.Namespace) -> None:
    paths = require_paths()
    conn = connect(paths.db_path)
    try:
        row = _snapshot_or_die(conn, args.snapshot)
        changes = get_file_changes(conn, row["id"])
        print(f"snapshot {row['id']}  {_fmt_ts(row['ts'])}")
        print(f"  agent:      {row['agent'] or 'unknown'} (confidence: {row['confidence']})")
        print(f"  kind:       {row['kind']}")
        if row["restored_from_id"]:
            print(f"  restored from snapshot: {row['restored_from_id']}")
        if row["prompt_text"]:
            print(f"  prompt:     {row['prompt_text']}")
        print(f"  commit:     {row['commit_sha']}")
        print()
        if not changes:
            print("  (no file changes)")
        else:
            for c in changes:
                print(f"  {c['change_type']}  {c['path']}  +{c['added']}/-{c['removed']}")
        if args.patch:
            store = ShadowStore(paths.store_dir, paths.root)
            print()
            print(store.show_text(row["commit_sha"]))
    finally:
        conn.close()


def cmd_diff(args: argparse.Namespace) -> None:
    paths = require_paths()
    conn = connect(paths.db_path)
    try:
        row_a = _snapshot_or_die(conn, args.a)
        row_b = _snapshot_or_die(conn, args.b)
    finally:
        conn.close()
    store = ShadowStore(paths.store_dir, paths.root)
    print(store.diff_text(row_a["commit_sha"], row_b["commit_sha"]))


def cmd_restore(args: argparse.Namespace) -> None:
    paths = require_paths()
    conn = connect(paths.db_path)
    try:
        target = _snapshot_or_die(conn, args.snapshot)
    finally:
        conn.close()

    engine = SnapshotEngine(paths)

    safety_id = engine.capture(
        agent="chronicle",
        confidence="none",
        kind="restore-safety",
        message=f"chronicle: safety snapshot before restoring to snapshot {target['id']}",
        force=True,
    )
    print(f"Safety snapshot taken (id {safety_id}). This restore can be undone.")

    engine.store.restore_worktree_to(target["commit_sha"])

    restore_id = engine.capture(
        agent="chronicle",
        confidence="none",
        kind="restore",
        restored_from_id=target["id"],
        message=f"chronicle: restored to snapshot {target['id']}",
        force=True,
    )
    print(f"Change undone. Working tree now matches snapshot {target['id']} (recorded as snapshot {restore_id}).")


def cmd_run(args: argparse.Namespace) -> None:
    paths = require_paths()
    if daemon_mod.is_running(paths) is None:
        print(
            "warning: daemon is not running -- nothing will be captured "
            "while this command runs. Start it with `chronicle daemon start`.",
            file=sys.stderr,
        )
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    exit_code = run_wrapper.run(paths, args.agent, cmd)
    raise SystemExit(exit_code)


def cmd_blame(args: argparse.Namespace) -> None:
    paths = require_paths()
    store = ShadowStore(paths.store_dir, paths.root)
    conn = connect(paths.db_path)
    try:
        sha = None
        if args.snapshot is not None:
            row = _snapshot_or_die(conn, args.snapshot)
            sha = row["commit_sha"]

        lines = store.blame(args.file, sha)
        if not lines:
            print(f"(no history for {args.file})")
            return

        for lineno, (line_sha, content) in enumerate(lines, start=1):
            snap = get_snapshot_by_sha(conn, line_sha)
            if snap is None:
                label = "?"
            else:
                conf = snap["confidence"] or "none"
                label = f"{snap['agent'] or 'unknown'} ({conf})"
            print(f"{lineno:>5}  {label:<26} {content}")
    finally:
        conn.close()


def cmd_hooks_install(args: argparse.Namespace) -> None:
    paths = require_paths()
    if args.tool != "claude-code":
        raise SystemExit(f"unknown tool: {args.tool!r} (only 'claude-code' is supported)")
    changed = install_claude_code_hooks(paths.root)
    settings_path = paths.root / ".claude" / "settings.json"
    if changed:
        print(f"Installed Claude Code hooks in {settings_path}")
    else:
        print(f"Claude Code hooks already installed in {settings_path}")


def cmd_hooks_status(args: argparse.Namespace) -> None:
    paths = require_paths()
    installed = claude_code_hooks_installed(paths.root)
    print(f"claude-code: {'installed' if installed else 'not installed'}")


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chronicle", description="The real edit history for AI-assisted repos.")
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="set up .chronicle/ in this project")
    p_init.add_argument("path", nargs="?", help="project root (default: cwd)")
    p_init.add_argument(
        "--hooks", dest="hooks", action="store_true", default=None,
        help="install Claude Code attribution hooks without prompting",
    )
    p_init.add_argument(
        "--no-hooks", dest="hooks", action="store_false",
        help="skip Claude Code attribution hooks without prompting",
    )
    p_init.set_defaults(func=cmd_init)

    p_daemon = sub.add_parser("daemon", help="manage the background watcher")
    daemon_sub = p_daemon.add_subparsers(dest="daemon_command", required=True)
    daemon_sub.add_parser("start", help="start the daemon").set_defaults(func=cmd_daemon_start)
    daemon_sub.add_parser("stop", help="stop the daemon").set_defaults(func=cmd_daemon_stop)
    daemon_sub.add_parser("status", help="is the daemon running?").set_defaults(func=cmd_daemon_status)

    p_ui = sub.add_parser("ui", help="open the local web UI (starts the daemon if needed)")
    p_ui.add_argument("--no-browser", action="store_true", help="print the URL instead of opening it")
    p_ui.set_defaults(func=cmd_ui)

    p_log = sub.add_parser("log", help="list recorded snapshots")
    p_log.add_argument("--agent", help="filter by agent")
    p_log.add_argument("--since", help="e.g. 30m, 2h, 3d, 1w")
    p_log.add_argument("--file", help="only snapshots touching this path")
    p_log.add_argument("--limit", type=int, default=50)
    p_log.set_defaults(func=cmd_log)

    p_show = sub.add_parser("show", help="show a snapshot's metadata and changes")
    p_show.add_argument("snapshot", type=int)
    p_show.add_argument("--patch", action="store_true", help="also print the full diff")
    p_show.set_defaults(func=cmd_show)

    p_diff = sub.add_parser("diff", help="diff between two snapshots")
    p_diff.add_argument("a", type=int)
    p_diff.add_argument("b", type=int)
    p_diff.set_defaults(func=cmd_diff)

    p_restore = sub.add_parser("restore", help="restore the working tree to a snapshot (linear, whole tree)")
    p_restore.add_argument("snapshot", type=int)
    p_restore.set_defaults(func=cmd_restore)

    p_run = sub.add_parser(
        "run", help="attribute a hook-less tool by wrapping it (tier 2)"
    )
    p_run.add_argument("--agent", required=True, help="agent name to attribute snapshots to")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- <command to run>")
    p_run.set_defaults(func=cmd_run)

    p_blame = sub.add_parser("blame", help="per-line: which agent wrote this?")
    p_blame.add_argument("file", help="path, relative to the project root")
    p_blame.add_argument("--snapshot", type=int, help="blame as of this snapshot (default: latest)")
    p_blame.set_defaults(func=cmd_blame)

    p_hooks = sub.add_parser("hooks", help="manage tool attribution hooks")
    hooks_sub = p_hooks.add_subparsers(dest="hooks_command", required=True)
    p_hooks_install = hooks_sub.add_parser("install", help="install hooks for a tool")
    p_hooks_install.add_argument("tool", choices=["claude-code"])
    p_hooks_install.set_defaults(func=cmd_hooks_install)
    hooks_sub.add_parser("status", help="show installed hooks").set_defaults(func=cmd_hooks_status)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except NotInitializedError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
