# SNI-Router UI

A dark-theme web console to **monitor and manage one or more
[sni-router](https://github.com/Ashteeer/sni-router) instances** — per-host
CPU / memory / network / connection charts, host inventory, and a visual + YAML
config editor that talks straight to each router's admin API.

Vue 3 · Vite · Tailwind · uPlot · CodeMirror — frontend. Python · FastAPI ·
stdlib SQLite · paramiko (remote install) — backend. Agent is Python stdlib only.

---

## Two components, two roles

The system is split into two independent pieces that you install and run
separately:

| | **Control plane** — the Site | **Data plane** — the Agent |
|---|---|---|
| What | The web app (FastAPI backend + Vue SPA) | A tiny stdlib metrics daemon |
| Runs on | One machine you open in a browser | Every host you want to monitor |
| Talks to | Each router's admin/metrics API + each agent | `/proc` + `statvfs` on its host |
| Serves | The UI, REST API, background poller, SQLite | `GET /sys` → CPU/RAM/disk/net JSON |
| Auth | **Login + password** (+ optional IP whitelist) | **Bearer token** (generated at install) |
| Installer | `scripts/install-site.sh` | `scripts/install-agent.sh` |
| Config file | `/etc/sni-router-ui/ui.conf` (editable in UI) | `/etc/sni-router-agent/agent.conf` (local) |

Why the agent exists: a router's admin API exposes **router** stats only
(connections, bytes, uptime). Host **CPU/RAM/disk/network** come from the agent —
one per managed host.

```
                 Browser (Vue SPA)
                     │  /api/*   login+password cookie (or IP whitelist)
                     ▼
        ┌─────────────────────────────┐
        │  SITE  (FastAPI, one proc)  │  serves SPA + REST + 5s poller
        │  SQLite: hosts + 2d metrics │  SSH client for remote installs
        └───┬─────────────┬───────────┘
   Bearer   │             │   SSH (install agent / sni-router, on demand)
   token    │             ▼
            │      managed host ── (1) AGENT  :PORT /sys      → cpu/mem/disk/net
            └────────────────────── (2) sni-router admin :9901 → status/config/ctl
                                     (2b) sni-router metrics :9100 /metrics → counters
```

---

## Quick start

Both installers are single Bash scripts. They download the component from GitHub,
write a local config, register a **systemd** service, start it, and print what you
need. Run them as root on the target host.

### 1. Install the Site (control plane)

On the machine that will host the console:

```bash
# defaults: listen on all interfaces, random free port, latest version
curl -fsSL https://raw.githubusercontent.com/Ashteeer/SNI-Router-UI/main/scripts/install-site.sh | sudo bash

# or pin the address / version:
curl -fsSL https://raw.githubusercontent.com/Ashteeer/SNI-Router-UI/main/scripts/install-site.sh \
  | sudo bash -s -- -s 0.0.0.0:8899 -v v1.0.0
```

Options: `-s IP:PORT` (bind; default all-IPs + random port) · `-v, --version`
(GitHub tag; default latest). It prints the URL — open it and complete the
one-time setup (admin login + optional IP whitelist). **Put TLS in front for
production** (sni-router itself can terminate it).

> Building the SPA needs Node 18+ on the site host. If `npm` is absent the
> installer stops and tells you; install Node and re-run, or copy a prebuilt
> `frontend/dist` into place.

### 2. Install an Agent (data plane) — on each host to monitor

```bash
# defaults: listen on all interfaces, random port, auto-generated token, latest
curl -fsSL https://raw.githubusercontent.com/Ashteeer/SNI-Router-UI/main/scripts/install-agent.sh | sudo bash

# or pin bind / token / version:
curl -fsSL https://raw.githubusercontent.com/Ashteeer/SNI-Router-UI/main/scripts/install-agent.sh \
  | sudo bash -s -- -a 0.0.0.0:9110 -t my-secret-token -v v1.0.0
```

Options: `-a IP:PORT` (bind; default all-IPs + random port) · `-t, --token`
(default auto-generated) · `-v, --version` (default latest). At the end it prints:

```
    IP:PORT   203.0.113.9:9110
    token     6f1c…e2a4
```

Paste those into the Site under **Hosts → Add Host** (Agent fields).

### …or skip the manual step: install remotely from the UI

Once the Site is up, **Hosts → Remote install** installs either the **metrics
agent** or **sni-router itself** on a remote host over SSH — no shell needed.
You give SSH host / user / password-or-key; the Site runs the installer, saves
the host with its generated token, and (for sni-router) drops a base config that
exposes the admin API + token on the interface you choose. SSH credentials are
used once and never stored.

---

## Configuration

Each component reads a plain `KEY=VALUE` file (systemd `EnvironmentFile`
compatible). **Only the site's own (local) config is editable from the web UI**
— the agent's config lives on its remote host.

- **Site:** `/etc/sni-router-ui/ui.conf` — `SNI_UI_HOST`, `SNI_UI_PORT`,
  `SNI_UI_DB`. Edit under **Settings** in the UI (host/port/DB changes need a
  service restart). See [`backend/ui.conf.example`](backend/ui.conf.example).
- **Agent:** `/etc/sni-router-agent/agent.conf` — `SNI_AGENT_TOKEN`,
  `SNI_AGENT_BIND`, `SNI_AGENT_PORT`. See
  [`agent/agent.conf.example`](agent/agent.conf.example).

The **Settings** tab also edits the IP whitelist (IPs/CIDRs that skip login).

---

## Authentication

- **Site:** username + password (created on first load, scrypt-hashed), carried
  by an HMAC-signed session cookie (7-day TTL). IP-whitelist entries bypass the
  login screen. The client IP is taken from `X-Real-IP` / `X-Forwarded-For`
  (set by the fronting proxy) else the socket peer.
- **Agent & router admin/metrics API:** `Authorization: Bearer <token>`. The
  agent's token is generated by its installer; the same token is stored per host
  in the Site and used to reach the router's admin API too.

---

## What's in the UI

- **Dashboard** — per-host CPU / memory / network / connection charts (uPlot,
  drag-to-zoom, 1h–2d) + stat tiles (uptime, active conns, disk, version).
- **Hosts** — add/remove routers, bulk delete, live Online/Offline, and
  **Remote install** (agent or sni-router over SSH).
- **Configs** — pick a host, edit its config as a **Visual** form or **Manual**
  YAML (CodeMirror), kept in sync; Save (`PUT /config`) and Restart go straight
  to that host's admin API.
- **Settings** — edit the site's local config + IP whitelist.

---

## Build from source

```bash
# frontend → produces frontend/dist, served by the backend
cd frontend && npm install && npm run build

# backend
cd ../backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8899
```

Agent (stdlib only, no build):

```bash
SNI_AGENT_TOKEN=<token> python3 agent/agent.py
python3 agent/agent.py selftest   # sanity check
```

See [`CLAUDE.md`](CLAUDE.md) for the full developer guide and
[`config.md`](config.md) for the authoritative sni-router config reference.

---

## Compatibility note

Some sni-router builds ship a **read-only** admin API — `PUT /config`,
`POST /reload`, `POST /restart` return `405`. Read features (status, config
view, metrics) work regardless; the UI surfaces the 405 on Save/Restart. Remote
sni-router provisioning is unaffected: the base config is written to disk
directly, not via the API. `/metrics` is served on its own port (`metrics.bind`,
default 9100), separate from `admin.bind` (default 9901).

Published: https://github.com/Ashteeer/SNI-Router-UI

## License

[MIT](LICENSE).
