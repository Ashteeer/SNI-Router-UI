#!/usr/bin/env python3
"""SNI-Router UI system-metrics agent.

Reads host stats from /proc + statvfs and serves them as JSON on GET /sys.
The sni-router admin API does not expose host CPU/RAM/disk, so this tiny agent
fills that gap. One per managed host.

ponytail: stdlib only, single file. Auth is a bearer token.

Config resolution (later wins): built-in defaults < config file < environment.
The config file is a plain KEY=VALUE file (same keys as the env vars) so systemd
can load it verbatim with EnvironmentFile=. Path from SNI_AGENT_CONF, default
/etc/sni-router-agent/agent.conf. This is the agent's LOCAL config — it lives on
the managed host and is written by the installer; the web UI never edits it.

    SNI_AGENT_TOKEN   required; requests must send `Authorization: Bearer <token>`
    SNI_AGENT_PORT    default 9110
    SNI_AGENT_BIND    default 0.0.0.0 (use 127.0.0.1 when the UI is co-located)
    SNI_AGENT_CONF    optional path to the KEY=VALUE config file

Self-check:  python3 agent.py selftest
"""
import http.server
import ipaddress
import json
import os
import socketserver
import ssl
import subprocess
import sys
import time
import urllib.parse

AGENT_VERSION = "1.11.2"
CONF_PATH = os.environ.get("SNI_AGENT_CONF", "/etc/sni-router-agent/agent.conf")


def load_conf(path):
    """Parse a KEY=VALUE file into a dict. Missing file -> {}. Blank lines and
    #-comments ignored; surrounding quotes on the value are stripped."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line[0] == "#" or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


_conf = load_conf(CONF_PATH)


def _cfg(key, default):
    return os.environ.get(key) or _conf.get(key) or default


TOKEN = _cfg("SNI_AGENT_TOKEN", "")
PORT = int(_cfg("SNI_AGENT_PORT", "9110"))
BIND = _cfg("SNI_AGENT_BIND", "0.0.0.0")


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


_ips_cache = {"at": 0, "val": []}


def ip_addrs():
    """Public IPv4 + IPv6 addresses assigned on this host, as CIDR strings.
    Only globally-routable addresses are returned — loopback, RFC1918 private,
    link-local (169.254/fe80::), ULA (fc00::/7) etc. are dropped. ponytail: shells
    out to `ip` (present on any modern Linux) and caches 60s so the 5s poller
    doesn't fork every tick."""
    now = time.time()
    if now - _ips_cache["at"] < 60:
        return _ips_cache["val"]
    out = []
    for fam, key in (("-4", "inet"), ("-6", "inet6")):
        try:
            text = subprocess.check_output(["ip", "-o", fam, "addr", "show"], text=True)
        except Exception:
            continue
        for line in text.splitlines():
            f = line.split()
            # "2: eth0    inet 1.2.3.4/24 brd ..." — token after inet/inet6
            if key not in f or f[1] == "lo":
                continue
            cidr = f[f.index(key) + 1]
            try:
                if ipaddress.ip_address(cidr.split("/")[0]).is_global:
                    out.append(cidr)
            except ValueError:
                continue
    _ips_cache.update(at=now, val=out)
    return out


def sample():
    mem_total, mem_used = meminfo()
    disk_total, disk_used = diskinfo()
    rx, tx = netinfo()
    return {
        "ts": int(time.time()),
        "version": AGENT_VERSION,
        "cpu_pct": cpu_percent(),
        "mem_total": mem_total,
        "mem_used": mem_used,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "net_rx": rx,
        "net_tx": tx,
        "ips": ip_addrs(),
        "load1": round(os.getloadavg()[0], 2),
        "ncpu": os.cpu_count(),
    }


def cert_info(path):
    """Inspect a TLS cert/key file on this host for the UI's Configs validation.
    Returns only metadata (existence, readability, and — for a certificate — its
    expiry), never file contents. Uses stdlib ssl to decode; a key or non-cert
    file just comes back is_cert=False. ponytail: token-gated like everything else."""
    if not path or not os.path.exists(path):
        return {"exists": False, "readable": False}
    if not os.access(path, os.R_OK):
        return {"exists": True, "readable": False}
    try:
        d = ssl._ssl._test_decode_cert(path)  # stdlib PEM decoder, no external deps
    except Exception:
        return {"exists": True, "readable": True, "is_cert": False}
    not_after = d.get("notAfter")
    expires = days = None
    try:
        expires = int(ssl.cert_time_to_seconds(not_after))
        days = int((expires - time.time()) // 86400)
    except Exception:
        pass
    cn = None
    for rdn in d.get("subject", ()):
        for k, v in rdn:
            if k == "commonName":
                cn = v
    return {"exists": True, "readable": True, "is_cert": True,
            "not_after": not_after, "expires_epoch": expires,
            "days_left": days, "subject_cn": cn}


TFO_SYSCTL = "/proc/sys/net/ipv4/tcp_fastopen"


def tfo_status():
    """Read net.ipv4.tcp_fastopen. Bit 2 (value & 2) = server-side TFO, which a
    listener needs to accept a client's TFO. Returns the raw value + that flag."""
    try:
        with open(TFO_SYSCTL) as f:
            v = int(f.read().strip())
    except Exception:
        return {"value": None, "enabled": False}
    return {"value": v, "enabled": bool(v & 2)}


def tfo_enable():
    """Turn on TFO for both client and server (value 3) at runtime and persist it
    across reboots. ponytail: agent runs as root, so it can write sysctl + /etc."""
    with open(TFO_SYSCTL, "w") as f:
        f.write("3\n")
    try:
        with open("/etc/sysctl.d/99-sni-router-tfo.conf", "w") as f:
            f.write("net.ipv4.tcp_fastopen = 3\n")
    except Exception:
        pass
    return tfo_status()


def start_update():
    """Fire the CLI updater in its own systemd transient scope so the agent's
    own `systemctl restart` (inside install-agent.sh) doesn't kill the updater
    mid-run by tearing down this unit's cgroup. Falls back to setsid.
    ponytail: needs the agent to run as root (it does) to write /opt + systemctl."""
    try:
        subprocess.Popen(
            ["systemd-run", "--collect", "--unit=sni-router-agent-update",
             "/usr/local/bin/sni-router-agent", "-u"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        subprocess.Popen(
            "setsid /usr/local/bin/sni-router-agent -u >/tmp/sni-agent-update.log 2>&1",
            shell=True, start_new_session=True,
        )


class Handler(http.server.BaseHTTPRequestHandler):
    def _auth_ok(self):
        return not TOKEN or self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth_ok():
            self.send_response(401); self.end_headers(); return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/sys":
            try:
                self._json(200, sample())
            except Exception as e:  # noqa: BLE001 — report, don't crash the thread
                self._json(500, {"error": str(e)})
            return
        if parsed.path == "/certcheck":
            p = (urllib.parse.parse_qs(parsed.query).get("path") or [""])[0]
            try:
                self._json(200, cert_info(p))
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
            return
        if parsed.path == "/tfo":
            try:
                self._json(200, tfo_status())
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self._auth_ok():
            self.send_response(401); self.end_headers(); return
        route = self.path.split("?")[0]
        if route == "/update":
            try:
                start_update()
                self._json(200, {"updating": True, "version": AGENT_VERSION})
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
            return
        if route == "/tfo":
            try:
                self._json(200, tfo_enable())
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
            return
        self.send_response(404); self.end_headers()

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
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "selftest":
        selftest()
    elif arg in ("version", "--version", "-v"):
        print(AGENT_VERSION)
    else:
        Server((BIND, PORT), Handler).serve_forever()
