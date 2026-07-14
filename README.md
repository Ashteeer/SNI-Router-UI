# SNI-Router UI

A modern, dark-theme web UI to monitor and manage one or more
[`sni-router`](config.md) instances — server metrics, host management, and a
live config editor with both a visual form and a raw YAML editor that stay in
sync.

## Features

- **Dashboard** — per-host CPU, memory, network I/O, and connection charts
  (drag-to-zoom, 1 hour → 2 day ranges) plus stat tiles: uptime, active
  connections, disk usage, version.
- **Hosts** — add/remove routers by admin IP, port, and API token; bulk delete;
  live online/offline status.
- **Configs** — pick a host and edit its config two ways:
  - a **Visual configurator** with mode-aware forms (listeners, routes,
    backends, TLS, headers, HTTP rules, timeouts, limits, logging), and
  - a **Manual** YAML editor (CodeMirror).

  The two stay synchronized — edit either side, the other updates, without
  clobbering each other. Save validates through the router and shows any errors
  inline; Restart re-execs the service.
- **Auth** — first-run admin setup, session login, and an optional IP whitelist
  that bypasses the login screen for trusted clients.

## Architecture

```
Browser (Vue 3 SPA)
   │  /api/*  (cookie session)
Backend (FastAPI)  ── serves the SPA, stores hosts + 2-day metrics in SQLite,
   │                  and polls every host on a schedule
   ├── sni-router admin API   (per host: status / config / reload / restart)
   └── metrics agent          (per host: CPU / RAM / disk / network from /proc)
```

The router's admin API only exposes router stats, so a tiny stdlib **metrics
agent** runs on each host to provide system metrics.

## Tech stack

Vue 3 · Vite · Tailwind CSS · uPlot · CodeMirror 6 — frontend.
Python · FastAPI · SQLite (stdlib) — backend and agent. No database server, no
heavyweight dependencies.

## Quick start (Ubuntu 24.04+)

```bash
# 1. Build the frontend
cd frontend && npm install && npm run build && cd ..

# 2. Run the backend (serves the built SPA + API)
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8899
```

Open `http://127.0.0.1:8899`, create the admin account, then add a host.

On each managed host, run the metrics agent (same token as the host's API token):

```bash
SNI_AGENT_TOKEN=<token> python3 agent/agent.py
```

systemd units for both the backend and the agent are in `backend/` and `agent/`.

## Security notes

- TLS is expected to be terminated in front of the UI (e.g. by sni-router
  itself); the backend listens on plain HTTP on a local port.
- Host API tokens are stored server-side and never sent to the browser.
- Passwords are hashed with scrypt; sessions are HMAC-signed cookies.

## Development

See [`CLAUDE.md`](CLAUDE.md) for the full developer guide (layout, API,
config-sync logic) and [`config.md`](config.md) for the sni-router config
reference the visual configurator is built from.

## License

[MIT](LICENSE).
