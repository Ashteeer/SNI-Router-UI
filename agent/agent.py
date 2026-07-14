#!/usr/bin/env python3
"""SNI-Router UI system-metrics agent.

Reads host stats from /proc + statvfs and serves them as JSON on GET /sys.
The sni-router admin API does not expose host CPU/RAM/disk, so this tiny agent
fills that gap. One per managed host.

ponytail: stdlib only, single file. Auth is a bearer token from the env.

    SNI_AGENT_TOKEN   required; requests must send `Authorization: Bearer <token>`
    SNI_AGENT_PORT    default 9110
    SNI_AGENT_BIND    default 0.0.0.0 (use 127.0.0.1 when the UI is co-located)

Self-check:  python3 agent.py selftest
"""
import http.server
import json
import os
import socketserver
import sys
import time

TOKEN = os.environ.get("SNI_AGENT_TOKEN", "")
PORT = int(os.environ.get("SNI_AGENT_PORT", "9110"))
BIND = os.environ.get("SNI_AGENT_BIND", "0.0.0.0")


def _cpu_times():
    with open("/proc/stat") as f:
        vals = list(map(int, f.readline().split()[1:]))
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
    return sum(vals), idle


def cpu_percent():
    t1, i1 = _cpu_times()
    time.sleep(0.1)
    t2, i2 = _cpu_times()
    dt, di = t2 - t1, i2 - i1
    return round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0


def meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            info[k] = int(rest.split()[0]) * 1024  # kB -> bytes
    total = info["MemTotal"]
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    return total, total - avail


def diskinfo(path="/"):
    s = os.statvfs(path)
    total = s.f_blocks * s.f_frsize
    free = s.f_bavail * s.f_frsize
    return total, total - free


def netinfo():
    rx = tx = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            iface, _, data = line.partition(":")
            if iface.strip() == "lo":
                continue
            fields = data.split()
            rx += int(fields[0])   # bytes received
            tx += int(fields[8])   # bytes transmitted
    return rx, tx


def sample():
    mem_total, mem_used = meminfo()
    disk_total, disk_used = diskinfo()
    rx, tx = netinfo()
    return {
        "ts": int(time.time()),
        "cpu_pct": cpu_percent(),
        "mem_total": mem_total,
        "mem_used": mem_used,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "net_rx": rx,
        "net_tx": tx,
        "load1": round(os.getloadavg()[0], 2),
        "ncpu": os.cpu_count(),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if TOKEN and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            return
        if self.path.split("?")[0] != "/sys":
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = json.dumps(sample()).encode()
        except Exception as e:  # noqa: BLE001 — report, don't crash the thread
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # quiet


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def selftest():
    s = sample()
    assert s["mem_total"] > 0 and s["mem_used"] >= 0
    assert 0.0 <= s["cpu_pct"] <= 100.0
    assert s["disk_total"] > 0
    assert s["net_rx"] >= 0 and s["net_tx"] >= 0
    print("ok", json.dumps(s))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        Server((BIND, PORT), Handler).serve_forever()
