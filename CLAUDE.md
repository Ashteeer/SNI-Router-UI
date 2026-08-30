# SNI-Router UI — developer guide

Web UI to monitor and manage one or more **sni-router** instances. Dark-theme
SPA + a small aggregation backend. This file is the source of truth — keep it
current.

> Config schema the UI targets: see [`config.md`](config.md) (the authoritative
> sni-router config reference).

## What it does

- **Dashboard** — per-host CPU / memory / network / connection charts (uPlot,
  drag-to-zoom, 1h–2d ranges) + stat tiles (uptime, active conns, disk, version).
  Bottom panel: software versions with **one-click self-update** (web UI + agent +
  **sni-router**, each vs its GitHub latest release) and the host's available IP
  addresses — **public IPv4 + IPv6 only** (the agent
  drops loopback/private/link-local), mask-aware (a range when the mask covers >1).
- **Hosts** — add/**edit**/remove sni-router instances, bulk delete. Each row
  shows **sni-router API** `ip:port` + live status **and** the **metrics agent**
  `agent_ip:agent_port` + live status. The agent may sit at a different IP than
  the router (`agent_ip`, blank = same as API IP). Pencil edits in place; a blank
  token/agent-token field keeps the stored one.
- **Configs** — pick a host, edit its config in a **Visual** form or a **Manual**
  YAML editor (CodeMirror). The two stay in sync. Save (`PUT /config`) and
  Restart (`POST /restart`) go straight to that host's admin API. Visual covers
  `default_tls` (shared cert), `log.level` and **Performance** (`runtime`); the
  header shows the host's IPs. Absent sections are stripped (never serialized as
  `key: null`) before save. A save that changes the router's **restart
  signature** asks for confirmation first (it re-execs and drops every live
  connection).
- **Settings** — change the **admin login/password** (no old-password check — the
  session is already authed), edit the site's **local** config (`ui.conf`) + IP
  whitelist.
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
(bumped per release; the agent embeds it as `AGENT_VERSION`). `install-agent.sh`
**seds `AGENT_VERSION` from the fetched `VERSION`** on every install/update, so a
self-update always moves the reported version even if the literal in `agent.py`
lagged — a stale literal once made the agent's "update available" stick forever
(the version never changed after updating). The backend
compares it to the latest GitHub release tag. Updating the web UI runs
`sni-router-ui -u` in a **systemd transient scope** (`systemd-run --collect`) so
the installer's own `systemctl restart` doesn't kill the updater by tearing down
its cgroup. The agent's `POST /update` does the same with `sni-router-agent -u`,
which is why the **agent now runs as root** (no `DynamicUser`) — it needs to
write `/opt` and call `systemctl`. Both installers are update-safe: re-running
them preserves the existing token/bind/port/DB. CLI: `sni-router-ui` /
`sni-router-agent` each take `-u|--update`, `-v|--version`, `-h|--help`.
**sni-router self-update** goes through the router's own admin API: the version
comes from `GET /status`, the latest tag from `Ashteeer/sni-router` releases, and
`POST /hosts/{id}/update` proxies the router's `POST /update` (downloads + re-execs
into the new binary — config.md §8.1). So the UI can view + update all three:
web UI, agent (per host), and sni-router (per host).

Why an agent: the sni-router admin API exposes router stats only (connections,
bytes, uptime). Host **CPU/RAM/disk/network** come from `agent/agent.py`, a
stdlib script reading `/proc` — one per managed host.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, httpx, paramiko (remote install).
  Storage: stdlib `sqlite3`. Auth: `hashlib.scrypt` + HMAC-signed cookie.
- **Agent:** Python stdlib only.
- **Frontend:** Vue 3 + Vite + Tailwind, uPlot (charts), CodeMirror 6 (editor),
  js-yaml (visual↔manual sync).

### UI design system (v1.11.0 redesign)

Dark-only **glassmorphism**: frosted `backdrop-blur` surfaces over an aurora
gradient body, one indigo→violet accent, soft glows. The aurora glows are painted
**directly on `body`** (`background-image` + `background-attachment: fixed`), *not*
a separate fixed `z-index:-1` layer — that layer was composited lazily by both
Chromium and Firefox and stayed blank until a scroll invalidated the root (the
"empty bg → gradient appears on scroll" bug; a `translateZ` compositor hint did
**not** fix it). The body background always paints on the first frame, and `fixed`
attachment keeps the glows viewport-anchored so a tall page has no hard scroll
edge. **Caveat:** `body` is `height:100%` (one viewport), so below the first
screen the glows exist only via body→canvas background propagation, which the
spec enables **only while `html` has no background of its own** — index.html's
anti-FOUC inline (`html,body{background:#080910}`) would kill it, so `style.css`
overrides with `html{background:transparent}`. Removing that override brings back
the "gradient ends after the first screen" bug on any scrollable page.
**All visual tokens are CSS
variables** in [`style.css`](frontend/src/style.css) (`--surface`, `--border`,
`--accent`, `--glow`, `--radius`, …) — retune the whole look in one place. Reusable
component classes (`.card` / `.card-hover`, `.btn-*`, `.input`, `.label`,
`.segment`/`.segment-btn`, `.nav-link`, `.dot`/`.dot-ok|bad|wait`, `.skeleton`)
back every screen; templates mostly compose these, so restyling is central.

- **Navigation:** sticky top navbar (brand + tab links + **global host switcher**
  shown on host-scoped tabs + logout) with a `md:hidden` **fixed bottom tab bar**
  on phones. No sidebar. The host switcher lives in `App.vue`, so Dashboard/Configs
  no longer carry their own host `<select>`.
- **Responsive:** everything reflows to ≤375px with no horizontal scroll. The
  Hosts table is desktop-only (`hidden md:block`); phones get a stacked **card
  list** (`md:hidden`) with the same data. Modals are `max-h`/scroll-safe.
- **Transitions/motion:** tab changes crossfade via a `<Transition name="view">`
  whose enter/leave share **one grid cell** (`grid-area:1/1`) — deliberately *not*
  `mode="out-in"`, so the incoming view mounts immediately and a stalled/paused
  transition (e.g. a backgrounded tab where `requestAnimationFrame` is frozen) can
  never leave the screen blank. Modals fade+scale (`<Transition name="modal">`),
  status dots pulse, tiles show `.skeleton` shimmers until live data lands.
- **Caveat:** view roots must **not** carry a CSS `animation` (e.g. a fade-in
  class) — Vue's `<Transition>` auto-detects it and waits for an `animationend`
  that never fires on leave, deadlocking the transition. Let the view transition
  own the entrance instead.

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
frontend/src/App.vue           auth gate + top navbar / mobile bottom-tabs + global host switcher + view transitions
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
| `GET/PUT /settings` | IP whitelist (+ `admin_user` on GET) |
| `PUT /account` | change admin login/password (authed; no old-pw check) |
| `GET/PUT /config` | site's local config (`ui.conf`) |
| `GET /version` (`?force=1` skips 1h cache) · `POST /update/ui` | UI+router latest-check · self-update |
| `POST /provision` | clean-install agent/router over SSH (`targets`, opt. `host_id`) |
| `GET /hosts` · `POST /hosts` · `PUT /hosts/{id}` · `DELETE /hosts/{id}` · `POST /hosts/delete` | host CRUD (PUT = edit; incl. `agent_ip`) |
| `GET /hosts/{id}/status` · `/live` · `/version` · `/history?range=1h\|6h\|24h\|48h` · `/agent` · `/certcheck?path=` · `/tfo` · `/netstat` | metrics · running router version (proxies router `GET /version`, falls back to `/status`) · agent `/sys` (IPs+version) · TLS cert/key check · host TFO sysctl status · curated kernel TcpExt counters, all via the agent |
| `POST /hosts/{id}/tfo` | ask the agent to enable `net.ipv4.tcp_fastopen = 3` on the host |
| `GET/PUT /hosts/{id}/config` · `POST /hosts/{id}/reload\|restart\|update\|agent-update` | config control · router self-update (proxies router `POST /update`) · agent self-update |

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
- `GET /config` redacts `api.token`; the backend re-injects the stored host token
  into both the GET (so the editor shows it) and the PUT (belt-and-suspenders), so
  the token is visible and never wiped on a GET→edit→save round-trip.

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
- [x] **v1.11.0 UI redesign** built (`vite build`, clean) and sandbox-tested on
  the german box in an isolated instance (own dir/port/DB, prod untouched): all
  four views render, glass tokens applied, tab transitions + modals work, host
  row/status dots bind live, mobile (375px) has no horizontal scroll and shows
  the bottom tab bar + card list. Pixel screenshots weren't captured (headless
  pane freezes rAF/paint) — verified via DOM + computed styles instead.
- [x] **v1.12.0 sni-router 1.8.0 support** built (`vite build`, clean) and tested
  against a stub admin API on Windows (venv backend + fake router serving
  `/version` `/status` `/config` `/metrics`): at **1.8.0** and **1.10.0** the
  `udp_idle` field renders and saves (`udp_idle: 45` reached the router's
  `PUT /config`); at **1.7.5** it is absent from the form *and* from the PUT body;
  with the router down it stays hidden. Inline validation verified live
  (`0` -> red "must be > 0", `500` -> amber ">300s"), and the PROXY-over-UDP note
  shows on the `dns` backend (udp listener + `proxy_protocol: v2`) but not on the
  tcp-only `web` backend. `GET /api/hosts/{id}/version` falls back to `/status`
  when the router has no `/version` (verified with the endpoint 404ing).
- [x] **v1.13.0 sni-router 1.9.0 support** (`runtime`) built (`vite build`,
  clean) and tested on Windows against two stub admin APIs (venv backend + fake
  routers on :9901 reporting 1.9.0 and :9902 reporting 1.8.0): on **1.9.0** the
  Performance card renders, the *High throughput* preset fills all four fields,
  `256 KiB` + the "~128 connections" pipe-budget warning show, and Save reaches
  the router with `runtime:` in the PUT body after confirming
  "can't be hot-swapped: runtime" (`{"applied":"restart","downtime":true}`).
  Every §3 validation row was exercised live (`io_uring_entries` 0 / 200 / 3000
  / 40000, `splice_chunk` 0 / 2048 / 1 MiB vs pipe, `pipe_size` 128 KiB / 2 MiB,
  `splice_spin` 100) — errors disabled Save, warnings did not. On **1.8.0** the
  card is replaced by the "needs 1.9.0+" note and the PUT body carries no
  `runtime` key. The confirm fires on a `log.level` change and stays quiet on a
  `servers` edit.
- [ ] **Not yet end-to-end tested:** installers (`scripts/*.sh`), local config
  editing (Settings), and SSH remote provisioning. Rebuild the frontend
  (`npm run build`) before shipping — the git tarball carries no `dist/`.
- Visual configurator covers listeners, backends (mode-aware), timeouts, limits,
  log, api. Anything it doesn't surface is always editable in Manual.
- **Mode/proto switches prune inapplicable fields.** Changing a backend's `mode`
  deletes every field the new mode doesn't use (per the `uses` matrix), and
  switching a listener to `udp` drops `fast_open`. Without this, the passthrough
  default's `servers: ['']` survived a switch to `redirect_https` and the router
  rejected the save (empty string is not a valid `IP:port`) — the rest would just
  raise "field ignored for this mode" warnings.
- **TCP Fast Open**, two independent switches (config.md §2.2, §3.4):
  - *listener* `fast_open` — accept TFO from clients. `proto: tcp` only (a hard
    config error on `udp`). Needs `net.ipv4.tcp_fastopen = 3` on the host; if
    unset the router still starts and only warns. **The UI checks this via the
    agent** (`GET /tfo`) when a listener's TFO is on: if the host sysctl isn't set
    it shows a yellow `!` next to the toggle; clicking it enables TFO on the host
    (`POST /tfo` → agent writes the sysctl + persists it) and toasts success.
  - *backend* `fast_open` — use TFO when connecting **to** `servers`. Every mode
    but `redirect_https` (which never connects to a backend).
- **Light observability** (agent `GET /netstat`): the Visual config shows host-wide
  kernel `TcpExt` counters inline next to the fields they relate to — accept-queue
  overflows (`ListenOverflows`) under **backlog**, and TFO queue overflows +
  accepted/failed under **fast_open_qlen** — green at 0, amber when climbing, with a
  ↻ refresh. Snapshot only (no history); the agent reads `/proc/net/netstat`.
- **Accept queues** (config.md §2.3): per-listener `backlog` and
  `fast_open_qlen`, both `tcp` only, both defaulting to 1024. `fast_open_qlen`
  only shows (and only survives) when `fast_open` is on. Empty input = omit the
  key: `0` is a hard error for both, so `setNum()` deletes rather than writing
  `Number('') === 0`. Same helper backs the timeouts, where clearing a field used
  to silently serialize an invalid `0`.
- **`timeouts.keepalive`** (config.md §5.1, default 60, `0` = off) — the only
  timeout where `0` is legal.
- **`timeouts.udp_idle`** (config.md §5.0, new in sni-router **1.8.0**, default 30)
  — the idle window for **plain** (non-QUIC) UDP flows: DNS, syslog. `idle` now
  covers **QUIC** flows plus the user-space reads in
  `terminate`/`terminate_tcp`/`redirect_https`; the router picks per flow by
  whether it ever saw a QUIC Initial. Inline validation: `0` is a hard error,
  `> 300` earns the router's WARNING (each live flow holds a backend socket, and
  a resolver takes a fresh source port per query — that is the whole reason the
  key was split out of `idle`).
- **`runtime` — "Performance" card** (config.md §6.5, new in sni-router **1.9.0**)
  — four optional ints on the TCP passthrough data path: `io_uring_entries`
  (ring depth per core), `splice_chunk` (bytes moved per go), `pipe_size` (the
  intermediate pipe `splice` needs) and `splice_spin` (rounds before a
  connection yields its core). Defaults show as **placeholders**, so the section
  can stay absent; an empty section is deleted rather than dumped as
  `runtime: {}`. Byte fields print a human size (`262144` → `256 KiB`). Three
  preset buttons (Defaults / Many connections / High throughput, values in
  config.md §6.5) plus **Clear**. Inline validation follows the router's table:
  `io_uring_entries` `0` or `> 32768` and `splice_chunk: 0` are **errors that
  disable Save** (the router would 400 the whole PUT), the rest are amber
  warnings — under 256 / not a power of two, `splice_chunk` under 4096 or above
  `pipe_size`, `pipe_size` over ~`fs.pipe-max-size`. The **key hint** is that
  none of these can add latency (the router never waits for a chunk to fill) —
  read as "bigger buffer = more lag", they get tuned backwards.
- **Pipe budget warning** — a passthrough connection holds **two** pipes and
  their pages count against `fs.pipe-user-pages-soft` (64 MiB default); past it
  the kernel silently hands out minimal pipes. So any `pipe_size > 64 KiB` shows
  the computed number of connections that still get the full size (256 KiB →
  ~128) and points at raising the sysctl.
- **Restart-signature confirm** (`Configs.vue`, `SIG_PARTS`) — sni-router
  hot-swaps routes/backends/timeouts but **re-execs** for listener
  `bind`/`proto`/`fast_open`/`backlog`/`fast_open_qlen`, terminate certs,
  `default_tls`, `api`, `log` and **`runtime`**, dropping every live connection.
  Save diffs those parts against the config as loaded and confirms, naming what
  changed; a plain `servers` edit saves without a prompt. Listener entries are
  compared as a **sorted set** so a drag-reorder isn't a false alarm. The
  baseline resets after a successful save.
- **Version gate** — the router parses its config with `deny_unknown_fields`, so
  a key it doesn't know **400s the entire `PUT`** and nothing is written.
  `VisualConfig` therefore fetches `GET /api/hosts/{id}/version` on every host
  switch and gates per feature: `udp_idle` joins `timeoutKeys()` at `>= 1.8.0`,
  the whole **Performance** card renders at `>= 1.9.0`; an unreachable router
  (version `null`) counts as *too old*. Comparison is numeric-segment
  (`verCmp`), not string — `1.10.0 > 1.8.0`. Hiding a field is also what keeps
  the key out of the saved YAML: an older router never returns it from
  `GET /config`, so the visual form is the only thing that could add it.
  (Manual YAML stays raw by design.)
- **PROXY protocol over UDP** (config.md §3.3) has **no config key** — the router
  frames it per flow (QUIC: one leading header datagram; plain UDP: a header on
  *every* datagram). The UI shows an amber note on any backend with
  `proxy_protocol: v1|v2` that a `proto: udp` listener routes to, including the
  Technitium checklist (*Optional Protocols* → DNS-over-UDP-PROXY on 538 **and**
  the router's IP in *Reverse Proxy Network ACL*, which defaults to empty and
  empty denies everyone — datagrams vanish with no log line).
- **HTTP/2 backend pooling** (config.md §3.10) has nothing to configure; the UI
  just points at `sni_router_h2_pool_hits_total` when `http2` is ticked.
  HTTP/1.1 terminate backends are pooled too (config.md §3.9) — also nothing to
  configure.
- Needs **sni-router ≥ 1.6.0** — older builds reject `backlog` /
  `fast_open_qlen` / backend `fast_open` as unknown fields. `udp_idle` needs
  ≥ **1.8.0** and is version-gated (above); everything else degrades gracefully.
- The UI does **not** parse sni-router's access log, so 1.8.0's new
  `mode="udp"` (vs the previous always-`quic` for UDP flows) needs no change
  here — noted so a future log viewer accounts for both values.
- **HTTP rules**: a per-rule *type* select with two zero/one-field presets —
  `301 → https/custom port` (sets `action:redirect status:301`, one `to` field:
  `https` for same-host:443, or a full URL for a custom port) and `404 Not Found`
  (`respond` 404 + body) — plus `forward`/`respond`/`redirect` for advanced use.
  `path` is a prefix match; `*` = all paths (no trailing `*` needed).
- **Drag-to-reorder** — interactive **pointer drag** (no dep): the grabbed card
  floats with the cursor (`translateY`) and a subtle `.drop-line` marks where it
  lands; `over` is the insertion index from sibling midpoints. Covers listeners,
  routes (within a listener), backends (map keys rebuilt), and http_rules — scoped
  by `kind`/`key` (queried via `:scope > [data-dragitem]`) so items can't cross
  categories. Window `pointermove`/`pointerup` listeners are cleaned up on unmount.
- **Rename a backend** rebuilds the map **in place** (no alphabetical jump) and
  **cascades** the new name to every `route.backend` that referenced the old one.
- **Timeout fields** carry a small `InfoTip` (`?`) with a one-line explanation each.
- **TLS cert/key validation** (`VisualConfig` needs `hostId`): every cert/key path
  is checked via the host agent's `GET /certcheck` — existence, readability, and
  (for a cert) `expires <date> — <n> days left` under `default_tls`. Checks run
  **automatically when a config loads** (a non-deep watch on `model`, keyed by
  `hostId`, so it fires once per host/reload — not on every keystroke) **and on
  blur** of a path field. Without the auto-check the expiry never showed unless the
  user happened to focus+blur the field, so it read as "cert duration missing on
  every host". The agent decodes with stdlib `ssl._ssl._test_decode_cert` +
  `ssl.cert_time_to_seconds`; it returns only metadata, never file contents.
- **Server IPs display as plain addresses** (`ip.js` `ipOnly`, mask stripped) — the
  earlier mask-aware range rendering (`cidrRange`) is kept in the file but unused.
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
