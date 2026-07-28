# chronicle web UI — design plan

Written before any component code, per the build plan (section 11). Checked
against the generic-default test at the bottom.

## The two things this UI is actually about

1. **Provenance under uncertainty.** Every row on screen makes a claim about
   who did something, and that claim has a confidence level. A hook-verified
   claim and a guessed one must never look the same at a glance.
2. **A branching structure, not a list.** `restore` creates a new snapshot
   that points back at an earlier one (`restored_from_id`). That back-edge is
   real graph structure already in the data model, even before phase 4 adds
   actual divergent branches -- it should be drawn as one, not hidden in a
   detail panel.

## Palette

Uses the dataviz skill's validated default categorical palette unchanged
(already CVD-checked in both light and dark; no reason to invent a new one
and skip validation). Two channels, deliberately kept separate:

- **Color = which agent.** Real AI agents (`claude-code`, `codex`, any custom
  name via `chronicle run --agent X`) get categorical hue slots, assigned in
  first-seen order per project: blue, orange, aqua, yellow, magenta, green,
  violet, red. `human` and `unknown` are not agents competing for identity --
  they get the neutral ink/muted role instead, which itself is informative
  ("nobody agent-like did this" reads differently from "some agent did
  this").
- **Shape/fill = how sure.** Confidence is never color-coded on top of
  identity -- that's two variables fighting over one channel. Every
  attribution renders as a small dot next to its agent name, always paired
  with a text label (never an icon alone):
  - **confident** (`hook` or `wrapper`) -- solid filled dot
  - **guessed** (`process`) -- dashed ring, ~60% fill opacity
  - **none** (`human` / `unknown`) -- hollow ring, muted ink, no hue

This is the signature element: the same dot renders in the timeline, the
detail panel, and per-line in blame, so "how sure are we" reads identically
everywhere in the product.

Chrome/ink roles (from the reference palette, both modes selected):

| Role | Light | Dark |
|---|---|---|
| Page plane | `#f9f9f7` | `#0d0d0d` |
| Surface | `#fcfcfb` | `#1a1a19` |
| Primary ink | `#0b0b0b` | `#ffffff` |
| Secondary ink | `#52514e` | `#c3c2b7` |
| Muted (human/unknown, axis) | `#898781` | `#898781` |
| Hairline | `#e1e0d9` | `#2c2c2a` |
| Border ring | `rgba(11,11,11,.10)` | `rgba(255,255,255,.10)` |

Categorical (agent) hues, light / dark:
blue `#2a78d6`/`#3987e5`, orange `#eb6834`/`#d95926`, aqua `#1baf7a`/`#199e70`,
yellow `#eda100`/`#c98500`, magenta `#e87ba4`/`#d55181`, green `#008300`/`#008300`,
violet `#4a3aa7`/`#9085e9`, red `#e34948`/`#e66767`.

## Typefaces

- **Display/UI face:** system sans (`-apple-system, "Segoe UI", sans-serif`)
  for headings, nav, buttons, labels, prose.
- **Data face:** system monospace (`ui-monospace, "SF Mono", Menlo, Consolas,
  monospace`) for everything that's structured/forensic data -- timestamps,
  file paths, commit SHAs, session IDs, diffs, blame lines.

Chosen deliberately, not defaulted: this is a tool about *evidence* --
timestamps and diffs read as records, not prose, and monospace says that
before you've read a word. No web fonts: chronicle runs fully offline, so
nothing here should depend on a network fetch.

## Layout concept

- Left rail: agent filter (checkboxes, one per seen agent + human/unknown,
  each with its dot), a file-path search, a date-range preset list, and the
  Timeline / Blame tab switcher.
- Main column: a vertical **spine** -- a hairline running down the left edge
  of the content, with each snapshot as a node on it (dot + agent name +
  timestamp + file count + label). Sequential snapshots connect by a
  straight segment of the spine. A `restore` node instead draws a curved
  dashed connector back up to the snapshot it restored, breaking out of the
  straight line -- the one place a graph shape earns its keep, because it's
  the one place the data actually isn't linear.
- Clicking a node opens a right-hand detail panel: full metadata, the diff
  (colorized unified diff), and the single action button, labeled for what
  it does: **"Undo this change."** On success the panel closes and a toast
  reads **"Change undone."** -- same words, start to finish, per the plan's
  copy rule.
- Blame view: a file-path field plus the file's lines, each prefixed with
  its confidence dot + agent name, colored by agent.
- Empty state (no snapshots yet): "No changes recorded yet. Start your
  agent and they'll appear here." -- an invitation, not an error.

## Quality floor

Responsive (rail collapses to a top drawer under ~720px), visible
`:focus-visible` rings using the border-ring token (never suppressed),
`prefers-reduced-motion: reduce` disables the spine's connector-draw
animation and the panel slide-in (both become instant).

## Generic-default test

Would this same page have been produced for any other dev tool? No: the
agent/confidence split into two independent channels (rather than one
overloaded color scale), the spine-with-a-back-edge for restores, and the
monospace-for-data / sans-for-chrome split are all specific to "who did
this, and how sure are we" being the actual content -- not decoration
layered onto a generic list-plus-modal admin panel.
