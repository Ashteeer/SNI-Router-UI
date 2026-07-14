"""Talks to each host: sni-router admin API + metrics agent.

- Proxies admin requests (status/config/reload/restart) for the API routes.
- Background poller samples every host every 5s into SQLite.
- Turns the stored cumulative counters into per-second rates for the charts.
"""
import asyncio
import time

import httpx

import db

POLL_INTERVAL = 5

# Prometheus metric name -> our column name
_PROM_KEYS = {
    "sni_router_connections_active": "conns_active",
    "sni_router_connections_total": "conns_total",
    "sni_router_bytes_up_total": "bytes_up",
    "sni_router_bytes_down_total": "bytes_down",
}


def admin_base(host):
    return f"http://{host['ip']}:{host['port']}"


def _auth_headers(host):
    return {"Authorization": f"Bearer {host['token']}"} if host.get("token") else {}


def _agent_headers(host):
    # the agent may run with its own token; blank = reuse the router api token
    tok = host.get("agent_token") or host.get("token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def admin_request(host, method, path, content=None, timeout=10):
    async with httpx.AsyncClient(timeout=timeout) as cl:
        return await cl.request(
            method,
            f"{admin_base(host)}{path}",
            content=content,
            headers=_auth_headers(host),
        )


def parse_prom(text):
    out = {}
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        # only the aggregate series (no {labels}); skip per-backend rows
        if name in _PROM_KEYS:
            try:
                out[_PROM_KEYS[name]] = int(float(parts[1]))
            except ValueError:
                pass
    return out


async def fetch_agent(host):
    port = host.get("agent_port") or 9110
    url = f"http://{host['ip']}:{port}/sys"
    async with httpx.AsyncClient(timeout=8) as cl:
        r = await cl.get(url, headers=_agent_headers(host))
        r.raise_for_status()
        return r.json()


async def poll_host(host):
    values = {"up": 0}
    # /metrics is served on the unified api bind (same port + token as admin).
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            r = await cl.get(f"{admin_base(host)}/metrics", headers=_auth_headers(host))
        if r.status_code == 200:
            values.update(parse_prom(r.text))
            values["up"] = 1
    except Exception:
        pass
    try:
        sys = await fetch_agent(host)
        for k in ("cpu_pct", "mem_used", "mem_total", "disk_used", "disk_total", "net_rx", "net_tx"):
            values[k] = sys.get(k)
    except Exception:
        pass
    db.insert_metric(host["id"], int(time.time()), values)


async def poll_loop():
    while True:
        try:
            for host in db.list_hosts():
                await poll_host(host)
            db.prune(int(time.time()) - db.RETENTION_SECS)
        except Exception:
            pass  # never let the loop die
        await asyncio.sleep(POLL_INTERVAL)


_RAW = ("cpu_pct", "mem_used", "mem_total", "disk_used", "disk_total",
        "conns_active", "conns_total", "up")
_RATE = {"net_rx": "net_rx_rate", "net_tx": "net_tx_rate",
         "bytes_up": "bytes_up_rate", "bytes_down": "bytes_down_rate"}


def build_history(rows):
    """Arrays for uPlot; cumulative counters become per-second rates."""
    out = {"ts": [r["ts"] for r in rows]}
    for col in _RAW:
        out[col] = [r[col] for r in rows]
    for col, name in _RATE.items():
        rates = []
        prev = None
        for r in rows:
            cur, ts = r[col], r["ts"]
            if prev and cur is not None and prev[0] is not None:
                dt = ts - prev[1]
                d = cur - prev[0]
                rates.append(round(d / dt, 1) if dt > 0 and d >= 0 else None)
            else:
                rates.append(None)
            prev = (cur, ts)
        out[name] = rates
    return out
