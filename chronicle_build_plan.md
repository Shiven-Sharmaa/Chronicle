# `chronicle` — the real edit history for AI-assisted repos

**Final year project build plan.** Phase 1 is a usable tool in a weekend. Phase 4 is the research contribution.

---

## 1. The one-line pitch

> Your coding agents each keep a private, temporary, incomplete diary. `chronicle` keeps the real one.

Claude Code, Codex, and Cursor each have their own checkpoint system. Each one is session-scoped, tool-scoped, expires, and only supports linear undo. `chronicle` sits underneath all of them and records what actually happened to the repository.

## 2. The gaps we're filling

| Gap | Status quo | `chronicle` |
|---|---|---|
| Changes made by `rm`/`mv`/shell | Not tracked, not undoable | Captured — we watch the filesystem |
| Manual edits, other tools, concurrent sessions | Not captured | Captured |
| History lifetime | Session-scoped, ~30 days | Permanent, project-scoped |
| Rollback shape | Linear only — going back to step 4 destroys 5–12 | Selective — remove step 4, keep 5–12 |
| Multiple agents at once | Nobody knows who did what | Per-change attribution |
| Cross-tool | Every tool reinvents it | One tool, works with all |

**Verify this table before you build.** Read the current Claude Code checkpointing docs at `https://code.claude.com/docs/en/checkpointing` and confirm each limitation still holds. If Anthropic closes one, your positioning shifts and you want to know before writing code, not at the viva.

---

## 3. Architecture

```
your-project/
├── .git/                    # untouched. we never write here.
├── .chronicle/
│   ├── store/               # shadow git dir — all snapshots live here
│   ├── chronicle.db         # sqlite: attribution, groups, test runs
│   ├── config.toml
│   └── daemon.sock
└── ... your files
```

Four components:

1. **Daemon** — filesystem watcher, debouncer, snapshot writer. Also an HTTP endpoint on localhost for hook adapters to post attribution hints.
2. **Shadow git store** — every snapshot is a commit in a *separate* git dir:
   ```
   git --git-dir=.chronicle/store --work-tree=. add -A
   git --git-dir=.chronicle/store --work-tree=. commit -m "snap N" --allow-empty
   ```
   You get git's delta compression, diffing, and worktrees. The user's `git log` never sees a thing. **This is non-negotiable** — tools that pollute commit history get uninstalled within a day.
3. **CLI** — `chronicle <verb>`.
4. **Local web UI** — served by the daemon, opened with `chronicle ui`.

**Stack:** Python 3.11+, `watchdog` for file events, `pygit2` or subprocess git, SQLite via stdlib, FastAPI for the local server, Vite + React for the UI. Package as `pipx install chronicle`.

---

## 4. Data model

```sql
CREATE TABLE snapshots (
  id          INTEGER PRIMARY KEY,
  commit_sha  TEXT NOT NULL,
  parent_id   INTEGER REFERENCES snapshots(id),
  ts          REAL NOT NULL,
  agent       TEXT,          -- 'claude-code' | 'codex' | 'human' | 'unknown'
  session_id  TEXT,
  tool        TEXT,          -- 'Edit' | 'Bash' | null
  confidence  TEXT           -- 'hook' | 'wrapper' | 'process' | 'none'
);

CREATE TABLE file_changes (
  snapshot_id INTEGER REFERENCES snapshots(id),
  path        TEXT,
  change_type TEXT,          -- 'A' | 'M' | 'D' | 'R'
  added       INTEGER,
  removed     INTEGER
);

CREATE TABLE groups (        -- one user intent -> many snapshots
  id          INTEGER PRIMARY KEY,
  label       TEXT,
  prompt_text TEXT,
  agent       TEXT,
  session_id  TEXT,
  started_ts  REAL,
  ended_ts    REAL
);

CREATE TABLE group_members (group_id INTEGER, snapshot_id INTEGER);

CREATE TABLE test_runs (
  snapshot_id INTEGER, command TEXT, exit_code INTEGER, ts REAL
);
```

`confidence` is deliberately explicit. Never show a guessed attribution as if it were certain — display it as "likely Codex" and let the UI dim it.

---

## 5. Capture

**Watcher.** `watchdog` observer on the repo root. Collect events into a buffer; flush to a snapshot after **400ms of quiet**. A single agent edit produces one snapshot; a burst of ten file writes during a refactor produces one snapshot, not ten.

**Exclusions.** Respect the user's `.gitignore` (shell out to `git check-ignore --stdin` in batches — don't reimplement gitignore semantics). Always exclude `.git/`, `.chronicle/`, `node_modules/`, `__pycache__/`, `.venv/`. Add a `max_file_size` config, default 5 MB, to avoid snapshotting build artifacts.

**Debounce edge case.** A long-running build writing files for 30 seconds will produce one enormous snapshot or many small ones depending on write pattern. Add a `max_batch_window` of 5s: flush regardless once the buffer is that old.

---

## 6. Attribution — three tiers

**Tier 1: hooks (high confidence).** Claude Code fires `PostToolUse` after each tool. Ship a hook script that POSTs to the daemon:

```json
{ "agent": "claude-code", "tool": "Edit", "session_id": "...",
  "prompt": "add rate limiting to the API", "ts": 1753... }
```

The daemon holds this as an active attribution context for a 3-second window. The next snapshot flush inside that window inherits it. Register via `.claude/settings.json`; `chronicle init` should offer to write this for the user.

Do the same for any other tool that exposes hooks. Check each tool's current docs — this surface changes often.

**Tier 2: process wrapper (high confidence).** For tools with no hooks:
```bash
chronicle run --agent codex -- codex
```
Every snapshot taken while that child process lives is attributed to it. Simple, honest, works with anything that has a CLI.

**Tier 3: process inspection (low confidence).** On flush with no active context, use `psutil` to look for known agent processes with the repo as cwd. If exactly one is running, attribute with `confidence='process'`. If zero or several, record `'human'` or `'unknown'`.

Design the UI so tier 3 never masquerades as tier 1.

---

## 7. Grouping

A raw stream of snapshots is unreadable. Group them into units a person recognises.

- **With hooks:** a group spans `UserPromptSubmit` → `Stop`. Perfect boundaries, and you get the prompt text as the label for free.
- **Without hooks:** cluster by time gap — a gap over 60 seconds starts a new group. Label from the files touched: "3 files in `src/auth/`".

The label is what makes the timeline scannable. Prefer the user's own words when you have them.

---

## 8. Selective revert — the research contribution

This is the part nothing else does, and the part your report is about.

**The problem.** Group 4 was a bad refactor. Groups 5–12 were good work. Linear rollback forces you to lose all of it. You want to remove only group 4.

**The pipeline:**

**Step 1 — reverse patch.** Compute group 4's cumulative diff, attempt `git apply -R --3way` onto the current tree.
- Applies cleanly → proceed to step 2.
- Conflicts → report exactly which later groups touched the conflicting hunks, and offer partial revert (per-file).

**Step 2 — dependency analysis.** *A clean text revert can still break the code.* If group 4 added `def validate_token()` and group 7 called it, reversing group 4's patch succeeds textually and leaves group 7 with a dangling reference.

Implementation:
1. Parse the group's diff to extract **symbols it introduced** — function, class, and module-level names. Use `tree-sitter` for multi-language; start with Python's `ast` module for a single-language MVP and expand.
2. Scan the current tree for **references** to those symbols outside the group's own files.
3. For each reference, report: symbol, the group that introduced the reference, and file:line.

Output looks like:

```
Reverting "add token validation" (group 4)

  Patch applies cleanly to 3 files.

  ⚠ 2 dependencies would break:
     validate_token()  — used in api/routes.py:88   (added by group 7)
     TokenError        — used in api/errors.py:12   (added by group 9)

  Revert anyway, revert and also remove dependents, or cancel?
```

That warning is the feature. Everything shipping today would silently leave you with broken code.

**Step 3 — verification.** If a test command is configured, run it before and after. If it was green and is now red, offer a one-key undo of the revert.

**Step 4 — safety.** Take a snapshot *immediately before* any restore or revert, always. The undo must itself be undoable. Non-negotiable.

**Honest scoping.** This is sound-ish, not sound. You're doing name-based reference matching, not full semantic analysis — dynamic dispatch, reflection, and string-based imports will slip through. Say so in the report and measure the miss rate. A measured false-negative rate is a result; a claim of soundness you can't back is a viva problem.

---

## 9. Agent bisect

```bash
chronicle bisect --command "pytest -q" --from <snap> --to <snap>
```

Binary search over snapshots. For each candidate, materialise it in a **separate worktree** so the user's live files are never touched:

```bash
git --git-dir=.chronicle/store worktree add /tmp/chronicle-bisect <sha>
```

Run the command there, record to `test_runs`, recurse. Output: the exact snapshot that flipped green to red, its diff, and its attributed agent.

Caveat to surface in the UI: this only works if the test command is self-contained. Anything depending on a database, network, or install state will give false results. Warn on first use.

---

## 10. CLI surface

```
chronicle init                          # set up .chronicle/, offer to install hooks
chronicle daemon start | stop | status
chronicle log [--agent X] [--since 2d] [--file path]
chronicle show <snapshot|group>
chronicle diff <a> <b>
chronicle restore <snapshot>            # linear rollback, whole tree
chronicle revert <group>                # selective, with dependency check
chronicle bisect --command "..."
chronicle blame <file>                  # per-line: which agent wrote this?
chronicle run --agent X -- <cmd>        # attribution wrapper
chronicle ui                            # open the web interface
```

`chronicle blame` is cheap to build on the shadow store and disproportionately compelling in a demo — open any file and see which agent authored each line.

---

## 11. The web UI

**Its single job:** let someone who just watched two agents work for an hour understand what happened and undo the wrong parts.

**Design direction.** Before writing components, write a short design plan — palette as 4–6 named hex values, a display face and a body face chosen deliberately, a layout concept, and one signature element. Then check it against a generic-default test: would you have produced this same page for any other developer tool? If yes, revise.

Two anchors specific to this subject:

- The content is **provenance under uncertainty**. Confidence tier should be legible at a glance — a hook-attributed change and a guessed one must never look identical. Let that distinction carry real visual weight rather than a small grey badge.
- The content is genuinely a **branching structure**, not a list. Restores create divergence. That's a rare case where a graph earns its place instead of decorating.

**Views:**
1. **Timeline** (default) — groups as rows, newest first, agent-labelled, file counts, expandable to snapshots. Filter by agent, file, date.
2. **Diff** — click any group or snapshot, see the change. Standard split diff.
3. **Revert flow** — the dependency warning from §8 is the most important screen in the product. Design it first, not last.
4. **Blame** — file view, lines tinted by authoring agent.

**Copy rules:** name things by what the user controls. "Undo this change," not "revert group 4." An action keeps the same name through the flow — the button that says "Undo this change" produces a toast that says "Change undone." Empty state is an invitation: "No changes recorded yet. Start your agent and they'll appear here."

**Quality floor, unannounced:** responsive, visible keyboard focus, `prefers-reduced-motion` respected.

---

## 12. Phases

### Phase 1 — usable core (a weekend)
`init`, daemon + watcher + debouncer, shadow git store, SQLite schema, `log`, `show`, `diff`, `restore` (with pre-restore safety snapshot).

**Ships as a real tool at this point.** It already captures things Claude Code's checkpointing cannot — bash-driven deletions, manual edits, other tools.

**Done when:** you run Claude Code, it does `rm src/old.py` via bash, and `chronicle restore` brings the file back. That single demo is the whole value proposition.

### Phase 2 — attribution (3–4 days)
Hook adapter for Claude Code, `chronicle run` wrapper, psutil fallback, confidence tiers, `chronicle blame`.

**Done when:** run Claude Code and Codex concurrently on one repo, then `chronicle log --agent codex` correctly isolates one agent's changes.

### Phase 3 — web UI (1 week)
FastAPI endpoints, Vite + React app, timeline and diff views.

**Done when:** someone who has never seen the CLI can open the UI and undo an agent's change.

### Phase 4 — selective revert (3–4 weeks) ← the research core
Grouping, reverse patch with conflict reporting, symbol extraction, dependency analysis, revert flow in the UI.

**Done when:** you can revert a middle group and get a correct dependency warning on a real agent session.

### Phase 5 — bisect (1 week)
Worktree-based binary search, test run recording, result view.

### Phase 6 — ship it (1 week)
`pipx` packaging, README with a recorded demo, `chronicle init` that works on a fresh machine, post it where agent users are.

**Real users are the strongest possible viva evidence.** Ten GitHub stars from people who actually installed it beats any amount of architecture diagram.

---

## 13. Evaluation (for the report)

Design these now — they shape what you log.

1. **Capture completeness.** Scripted agent sessions with known ground-truth changes, including bash-driven ones. Measure what fraction `chronicle` captures vs what Claude Code's own checkpointing captures. Expect a clear win on the bash and manual-edit categories; report honestly where you tie.
2. **Attribution accuracy.** Scripted concurrent Claude Code + Codex sessions with ground truth. Precision/recall per confidence tier. The interesting number is how much worse tier 3 is than tier 1.
3. **Selective revert.** Collect 20–30 real agent sessions. For each group, attempt revert. Report: clean-apply rate, conflict rate, dependency warnings raised, and — the key metric — how many reverts that applied cleanly *would have* broken the build without the warning.
4. **Bisect.** Inject faults at known snapshots, measure localisation accuracy and steps vs linear scan.
5. **Overhead.** Daemon CPU and memory, snapshot latency, storage growth per hour of agent work on repos of varying size. If this is heavy, nobody keeps it running.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Storage growth on large repos | Delta compression is git's job; add retention config and `chronicle gc` |
| Watcher misses very rapid writes | `max_batch_window` flush; test with a script writing 1000 files |
| `.gitignore` semantics are subtle | Shell out to `git check-ignore`, never reimplement |
| Agent tools change their hook APIs | Adapters are isolated modules; core works with zero adapters |
| Anthropic ships selective revert | Your differentiator is cross-tool + persistent + filesystem-level. Don't build only the revert. |
| Attribution is wrong and users trust it | Confidence tiers, visually distinct, everywhere |

---

## 15. Before you start

Verify against current docs rather than this plan — all of these move:

- Claude Code checkpointing limits: `https://code.claude.com/docs/en/checkpointing`
- Claude Code hooks events and payload shape: `https://code.claude.com/docs/en/hooks`
- Codex's current extension surface, whatever it is this month

If any of the gaps in §2 has closed, adjust the pitch before writing code.
