# SNI-Router UI — developer guide

Web UI to monitor and manage one or more **sni-router** instances. Dark-theme
SPA + a small aggregation backend. This file is the source of truth — keep it
current.

> Config schema the UI targets: see [`config.md`](config.md) (the authoritative
> sni-router config reference).

## What it does

- **Dashboard** — per-host CPU / memory / network / connection charts (uPlot,
  drag-to-zoom, 1h–2d ranges) + stat tiles (uptime, active conns, disk, version).
- **Hosts** — add/remove sni-router instances (name, admin IP, port, API token),
  bulk delete, live Online/Offline check.
- **Configs** — pick a host, edit its config in a **Visual** form or a **Manual**
  YAML editor (CodeMirror). The two stay in sync. Save (`PUT /config`) and
  Restart (`POST /restart`) go straight to that host's admin API.

## Architecture

```
Browser (Vue SPA)
   │  /api/*  (cookie session)
Backend (FastAPI, one process)         ── serves built SPA + REST + poller
   │  http                              stores hosts + 2-day metrics in SQLite
   ├── sni-router admin API  (per host, IP:port, Bearer token)
   │      GET /status /config /metrics · PUT /config · POST /reload /restart
   └── metrics agent         (per host, :9110, same token)  GET /sys
```

Why an agent: the sni-router admin API exposes router stats only (connections,
bytes, uptime). Host **CPU/RAM/disk/network** come from `agent/agent.py`, a
stdlib script reading `/proc` — one per managed host.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, httpx. Storage: stdlib `sqlite3`.
  Auth: `hashlib.scrypt` + HMAC-signed cookie (no extra deps).
- **Agent:** Python stdlib only.
- **Frontend:** Vue 3 + Vite + Tailwind, uPlot (charts), CodeMirror 6 (editor),
  js-yaml (visual↔manual sync).

## Layout

```
agent/agent.py                 system-metrics agent (+ .service unit)
backend/app.py                 FastAPI: auth, hosts, admin proxy, SPA serving
backend/db.py                  SQLite: settings, hosts, metrics time-series
backend/collector.py           admin proxy helpers + poller + rate math
frontend/src/App.vue           auth gate + sidebar + tab routing
frontend/src/views/            Login, Dashboard, Hosts, Configs
frontend/src/components/       UChart (uPlot), Editor (CodeMirror), VisualConfig
config.md                      sni-router config reference (schema source)
```

## Build & run

Frontend build (produces `frontend/dist`, served by the backend):
```bash
cd frontend && npm install && npm run build
```

Backend:
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8899
```
Open the UI on `http://127.0.0.1:8899`. First load shows a one-time setup screen
(create admin user + optional IP whitelist). TLS is expected to be terminated
in front of the UI (e.g. by sni-router itself).

Agent (on each managed host):
```bash
SNI_AGENT_TOKEN=<same-as-host-api-token> python3 agent/agent.py
# selftest: python3 agent/agent.py selftest
```

systemd units: `backend/sni-router-ui.service`, `agent/sni-router-agent.service`
(both assume `/opt/sni-router-ui`). Adjust paths/token, then enable.

## API (all under `/api`, cookie-authed unless noted)

| Method + path | purpose |
|---|---|
| `GET /me` | auth/setup state (unauth) |
| `POST /setup` · `POST /login` · `POST /logout` | first-run / session |
| `GET/PUT /settings` | IP whitelist |
| `GET /hosts` · `POST /hosts` · `DELETE /hosts/{id}` · `POST /hosts/delete` | host CRUD |
| `GET /hosts/{id}/status` · `/live` · `/history?range=1h\|6h\|24h\|48h` | metrics |
| `GET/PUT /hosts/{id}/config` · `POST /hosts/{id}/reload\|restart` | config control (proxied w/ token) |

## Config sync logic (Configs tab)

Source of truth is the parsed config object (`model`).
- **Manual → visual:** editor emits *user* edits only → `js-yaml.load` → replace
  `model` (a guard flag stops the echo back to text). Parse errors pause the
  visual view without discarding text.
- **Visual → manual:** a deep watcher on `model` re-dumps YAML into the editor;
  `Editor.vue` applies programmatic doc changes with an annotation so they are
  **not** re-emitted as user edits. This is what prevents the two from
  overwriting each other.
- Save sends the editor's YAML verbatim; sni-router validates and returns
  `{applied: reload|restart, downtime}` or a `{errors:[...]}` list (shown inline).

## Auth / IP whitelist

Session = HMAC-signed cookie (7-day TTL). IP whitelist entries (IPs or CIDRs)
bypass login; the client IP is taken from `X-Real-IP`/`X-Forwarded-For` (set by
the fronting sni-router) else the socket peer. Admin password is scrypt-hashed.

## Status

- [x] Backend, agent, full frontend (all three tabs) implemented.
- [ ] End-to-end tested against a live sni-router.
- Visual configurator covers listeners, backends (mode-aware), timeouts, limits,
  log, metrics, admin. Anything it doesn't surface is always editable in Manual.

## Conventions / notes

- `ponytail:` comments mark deliberate simplifications (e.g. single DB lock).
- Never commit tokens, keys, `.db` files, or real host configs (see `.gitignore`).
- Agent port defaults to 9110 and reuses the host's API token.
