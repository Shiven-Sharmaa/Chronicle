# chronicle

> Your coding agents each keep a private, temporary, incomplete diary. `chronicle` keeps the real one.

Claude Code, Codex, and Cursor each have their own checkpoint system: session-scoped, tool-scoped, expiring, linear-undo-only. `chronicle` sits underneath all of them and records what actually happened to your repository — including `rm`, `mv`, manual edits, and anything else that isn't a tool call.

This repo currently implements **Phases 1–3** of the build plan: a usable standalone tool with per-agent attribution and a local web UI.

## What it does today

- Watches your project's files (a `watchdog` filesystem observer, debounced so a burst of writes becomes one snapshot).
- Snapshots the working tree into a **shadow git store** at `.chronicle/store` — a separate git directory from your real `.git`. Your `git log` never sees it.
- Records each snapshot's metadata (timestamp, files changed, lines added/removed, attributed agent) in `.chronicle/chronicle.db` (SQLite).
- Lets you inspect and roll back history with a CLI.
- Attributes each snapshot to whichever agent made it, across three tiers of decreasing confidence:
  1. **hooks** (`confidence=hook`) — Claude Code's `PostToolUse`/`UserPromptSubmit` hooks POST directly to the daemon in real time. `chronicle init` offers to install them (or run `chronicle hooks install claude-code` any time).
  2. **process wrapper** (`confidence=wrapper`) — `chronicle run --agent codex -- codex` attributes everything that happens while that child process is alive. Works with any hook-less CLI tool.
  3. **process inspection** (`confidence=process`) — if neither of the above applies, `psutil` looks for a known agent CLI process with this repo as its cwd. Attributed only if exactly one candidate is found; otherwise recorded as `human` (nothing agent-like running) or `unknown` (more than one candidate, genuinely ambiguous).
- `chronicle blame <file>` — per-line attribution, built directly on `git blame` against the shadow store (every snapshot is already a real commit).
- `chronicle ui` — a local web UI (FastAPI + React, served by the daemon over plain TCP on `127.0.0.1`): a timeline of every snapshot, a diff/undo panel, and a blame view. Design plan and rationale in `webui/DESIGN.md`.

Selective revert with dependency analysis and bisect are Phase 4+ and not built yet.

## Install (dev)

```bash
uv venv --python 3.12
uv pip install -e . --group dev

# build the web UI once (needed for `chronicle ui` to serve anything)
cd webui && npm install && npm run build && cd ..
```

## Usage

```bash
cd your-project
chronicle init             # sets up .chronicle/, takes a baseline snapshot
chronicle daemon start     # begins watching

# ... let an agent (or yourself) edit files, run `rm`, whatever ...

chronicle log                    # see recorded snapshots
chronicle log --file src/api.py  # only snapshots touching a path
chronicle show <id> --patch      # metadata + full diff for one snapshot
chronicle diff <a> <b>           # diff between two snapshots
chronicle restore <id>           # restore the whole tree to a snapshot
                                  # (always takes a safety snapshot first —
                                  #  restoring is itself undoable)
chronicle blame src/api.py       # per-line: which agent wrote this?

chronicle daemon stop
chronicle daemon status
chronicle ui                     # open the web UI (starts the daemon if needed)

# Attribution
chronicle hooks install claude-code   # per-tool attribution via Claude Code hooks
chronicle hooks status
chronicle run --agent codex -- codex  # wrap a hook-less tool instead
chronicle log --agent codex           # isolate one agent's changes
```

## Design notes

- **Never touches your real `.git`.** All snapshotting happens via `git --git-dir=.chronicle/store --work-tree=.`.
- **History is append-only.** `restore` never rewrites or resets the shadow store's history — it commits a new snapshot whose tree matches the target. The undo is itself undoable, always.
- **Exclusions** respect your `.gitignore` (via `git check-ignore`, never reimplemented) plus static excludes (`.git`, `.chronicle`, `node_modules`, `__pycache__`, `.venv`, ...).
- **Attribution is honest about uncertainty.** Every snapshot has a `confidence` field, and tier 3 (process inspection) is a guess by design — it never claims tier 1/2 confidence. Tier 3 only matches on the executable name and its first argument (not the full command line): matching the whole cmdline text is a real trap, since unrelated processes can carry long argument strings that happen to contain a needle like "claude" somewhere deep inside — discovered by hand during testing, not hypothetical.
- **The UI never lets a guess look like a fact.** Confidence renders as its own visual channel (solid dot = confident, dashed = guessed, hollow = no signal) that's completely separate from the agent's color — never overloading one channel with two meanings. Full rationale in `webui/DESIGN.md`.
- **The web UI talks to the daemon over plain TCP** (`127.0.0.1`, default port 4317, auto-incrementing if taken), separate from the Unix-socket endpoint hooks POST to — a browser can't open a UDS connection.

## Tests

```bash
uv run pytest -q
```

Includes end-to-end tests that drive the real CLI/daemon as subprocesses:
- The Phase 1 demo: create a file, let the daemon capture it, delete it via `rm` (simulating an agent's bash tool call), then `chronicle restore` it.
- The Phase 2 demo: Claude Code (via a real hook POST) and Codex (via `chronicle run`) make concurrent changes, and `chronicle log --agent <x>` correctly isolates each one's files.
- The Phase 3 API surface (`tests/test_webapp.py`) against a real FastAPI `TestClient`, and `chronicle ui` actually starting the daemon and serving a working port (`tests/test_ui_cli.py`).

The web UI itself was also driven with a real headless Chromium (Playwright) against live multi-agent history during development — not just unit-tested — which is how the AF_INET/uvicorn `fd=` bug and a mobile z-index stacking bug (`webui/src/index.css`) were actually caught.
