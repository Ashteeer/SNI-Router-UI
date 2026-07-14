# SNI-Router UI — developer guide

Web UI to monitor and manage one or more **sni-router** instances. Dark-theme
SPA + a small aggregation backend. This file is the source of truth — keep it
current.

> Config schema the UI targets: see [`config.md`](config.md) (the authoritative
> sni-router config reference).

## What it does

- **Dashboard** — per-host CPU / memory / network / connection charts (uPlot,
  drag-to-zoom, 1h–2d ranges) + stat tiles (uptime, active conns, disk, version).
  Bottom panel: software versions with **one-click self-update** (web UI + agent)
  and the host's available IP addresses — **public IPv4 + IPv6 only** (the agent
  drops loopback/private/link-local), mask-aware (a range when the mask covers >1).
- **Hosts** — add/**edit**/remove sni-router instances, bulk delete. Each row
  shows **sni-router API** `ip:port` + live status **and** the **metrics agent**
  `agent_ip:agent_port` + live status. The agent may sit at a different IP than
  the router (`agent_ip`, blank = same as API IP). Pencil edits in place; a blank
  token/agent-token field keeps the stored one.
- **Configs** — pick a host, edit its config in a **Visual** form or a **Manual**
  YAML editor (CodeMirror). The two stay in sync. Save (`PUT /config`) and
  Restart (`POST /restart`) go straight to that host's admin API. Visual covers
  `default_tls` (shared cert) and `log.level`; the header shows the host's IPs.
  Absent sections are stripped (never serialized as `key: null`) before save.
- **Settings** — edit the site's **local** config (`ui.conf`) + IP whitelist.
- **Remote install** (Hosts tab) — **clean-install** the metrics agent and/or
  sni-router (checkboxes) on a remote host over SSH (paramiko), then create a new
  host or **overwrite an existing one** (new/update tabs). Clean install wipes old
  config; a fresh token is generated. (In-dashboard version updates preserve config.)

## Architecture

```
Browser (Vue SPA)
   │  /api/*  (cookie session)
Backend (FastAPI, one process)         ── serves built SPA + REST + poller
   │  http                              stores hosts + 2-day metrics in SQLite
   ├── sni-router admin API  (per host, IP:port, Bearer token)
   │      GET /status /config /metrics · PUT /config · POST /reload /restart
   └── metrics agent         (per host, :9110, same token)  GET /sys · POST /update
```

**Self-update:** the repo-root `VERSION` file is the single source of truth
(bumped per release; the agent embeds it as `AGENT_VERSION`). The backend
compares it to the latest GitHub release tag. Updating the web UI runs
`sni-router-ui -u` in a **systemd transient scope** (`systemd-run --collect`) so
the installer's own `systemctl restart` doesn't kill the updater by tearing down
its cgroup. The agent's `POST /update` does the same with `sni-router-agent -u`,
which is why the **agent now runs as root** (no `DynamicUser`) — it needs to
write `/opt` and call `systemctl`. Both installers are update-safe: re-running
them preserves the existing token/bind/port/DB. CLI: `sni-router-ui` /
`sni-router-agent` each take `-u|--update`, `-v|--version`, `-h|--help`.

Why an agent: the sni-router admin API exposes router stats only (connections,
bytes, uptime). Host **CPU/RAM/disk/network** come from `agent/agent.py`, a
stdlib script reading `/proc` — one per managed host.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, httpx, paramiko (remote install).
  Storage: stdlib `sqlite3`. Auth: `hashlib.scrypt` + HMAC-signed cookie.
- **Agent:** Python stdlib only.
- **Frontend:** Vue 3 + Vite + Tailwind, uPlot (charts), CodeMirror 6 (editor),
  js-yaml (visual↔manual sync).

## Layout

```
agent/agent.py                 system-metrics agent (reads agent.conf; + .service)
agent/agent.conf.example       agent local config (token/bind/port)
backend/app.py                 FastAPI: auth, hosts, admin proxy, provision, SPA
backend/db.py                  SQLite: settings, hosts, metrics time-series
backend/collector.py           admin proxy helpers + poller + rate math
backend/uiconf.py              site local config (ui.conf) load/read/write
backend/ssh.py                 paramiko wrapper (run / put / put_root)
backend/provision.py           SSH orchestration: install agent / sni-router
backend/ui.conf.example        site local config (host/port/db)
scripts/install-agent.sh       agent installer (-v, -a IP:PORT, -t token)
scripts/install-site.sh        site installer (-v, -s IP:PORT)
frontend/src/App.vue           auth gate + sidebar + tab routing
frontend/src/views/            Login, Dashboard, Hosts, Configs, Settings
frontend/src/components/       UChart (uPlot), Editor (CodeMirror), VisualConfig
config.md                      sni-router config reference (schema source)
```

Config files are plain `KEY=VALUE` (systemd `EnvironmentFile`-compatible).
`uiconf` folds `ui.conf` into the env on import (before `db` reads it); only the
site's own config is editable from the UI (agent config is remote/local-to-host).
Installers write these files and register the systemd units.

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
| `GET/PUT /config` | site's local config (`ui.conf`) |
| `GET /version` · `POST /update/ui` | UI version/latest-check · self-update |
| `POST /provision` | clean-install agent/router over SSH (`targets`, opt. `host_id`) |
| `GET /hosts` · `POST /hosts` · `PUT /hosts/{id}` · `DELETE /hosts/{id}` · `POST /hosts/delete` | host CRUD (PUT = edit; incl. `agent_ip`) |
| `GET /hosts/{id}/status` · `/live` · `/history?range=1h\|6h\|24h\|48h` · `/agent` | metrics · agent `/sys` (IPs+version) |
| `GET/PUT /hosts/{id}/config` · `POST /hosts/{id}/reload\|restart\|agent-update` | config control · agent self-update |

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

## Remote provisioning (SSH)

`provision.provision(p)` **clean-installs** the selected `targets` (`agent`
and/or `router`) on a remote host over SSH (`ssh.py`, paramiko), from the single
`POST /provision` endpoint via `asyncio.to_thread`. SSH creds are per-request and
**never stored**. One fresh token is generated and shared by both. Agent: the
local `scripts/install-agent.sh` is uploaded and run **with `--purge`** (wipes any
old dir/config first). sni-router: their `install.sh` is piped to bash, the old
config is removed, then a **base config** (API-only, `api.bind` + `token`) is
written to `/etc/sni-router/sni-router.yaml` (0640, chowned) and the service
enabled. Then create a new host row or **overwrite an existing one** (`host_id`):
`ip`+`port`+`token` for the router, `agent_ip`+`agent_port`+`agent_token` for the
agent. No sni-router changes were needed — provisioning writes the config directly,
so even a read-only-admin build works.

## Status

- [x] Backend, agent, full frontend (Dashboard/Hosts/Configs/Settings) implemented.
- [x] End-to-end tested on Ubuntu 24.04: dashboard/metrics/hosts/config-read
  against a live sni-router; config save/validation-errors/restart against a
  router that implements the documented write API.
- [ ] **Not yet end-to-end tested:** installers (`scripts/*.sh`), local config
  editing (Settings), and SSH remote provisioning. Frontend not rebuilt since
  these UI additions — run `npm run build` before shipping.
- Visual configurator covers listeners, backends (mode-aware), timeouts, limits,
  log, api. Anything it doesn't surface is always editable in Manual.
- Published: https://github.com/Ashteeer/SNI-Router-UI

### Compatibility note

Some sni-router builds ship a **read-only** admin API — `PUT /config`,
`POST /reload`, and `POST /restart` return `405 Method Not Allowed`. Read
features (status, config view, metrics) work regardless; the UI surfaces the 405
as an error on Save/Restart. `/status`, `/config`, `/metrics` and the control
endpoints all share **one bind + one token** (config.md §8, `api.bind`, default
port 9901) — the UI stores that single port + token per host (plus `agent_port`
for the metrics agent, which reuses the same token).

## Conventions / notes

- `ponytail:` comments mark deliberate simplifications (e.g. single DB lock).
- Never commit tokens, keys, `.db` files, or real host configs (see `.gitignore`).
- Agent port defaults to 9110 and reuses the host's API token.
