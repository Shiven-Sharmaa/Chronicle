# chronicle web UI

The local web UI: a Vite + React + TypeScript app, served by the daemon
(`chronicle ui`). See `DESIGN.md` for the design plan and rationale, and the
top-level `README.md` for how this fits into the rest of chronicle.

## Develop

```bash
npm install
npm run dev
```

Proxies `/api` to `http://127.0.0.1:4317` (the daemon's default port), so run
`chronicle daemon start` in a project first.

## Build

```bash
npm run build
```

Outputs straight into `../src/chronicle/webui_dist`, which the daemon serves
directly — no separate copy step.
