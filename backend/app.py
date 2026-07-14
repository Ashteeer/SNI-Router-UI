"""SNI-Router UI backend.

Single FastAPI process: serves the built SPA, exposes /api/*, proxies to each
host's sni-router admin API, and runs the background metrics poller.
"""
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import uiconf  # noqa: F401 — import first: folds ui.conf into the env before db reads it
import collector
import db
import provision

SESSION_TTL = 7 * 86400  # 7 days
ROOT = os.path.join(os.path.dirname(__file__), "..")
DIST = os.path.join(ROOT, "frontend", "dist")
REPO = "Ashteeer/SNI-Router-UI"


# ---------- auth primitives (stdlib only) ----------
def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ":" + dk.hex()


def check_pw(pw, stored):
    try:
        salt_hex, dk_hex = stored.split(":")
        dk = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _secret():
    s = db.get_setting("secret")
    if not s:
        s = secrets.token_hex(32)
        db.set_setting("secret", s)
    return s


def sign_session(username):
    payload = {"u": username, "exp": int(time.time()) + SESSION_TTL}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def verify_session(token):
    try:
        body, sig = token.rsplit(".", 1)
        good = hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload if payload.get("exp", 0) >= time.time() else None
    except Exception:
        return None


def client_ip(request: Request):
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def ip_allowed(ip, whitelist):
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif ipaddress.ip_address(entry) == addr:
                return True
        except ValueError:
            continue
    return False


def whitelist():
    return json.loads(db.get_setting("ip_whitelist") or "[]")


def current_user(request: Request):
    tok = request.cookies.get("session")
    if tok:
        p = verify_session(tok)
        if p:
            return p["u"]
    wl = whitelist()
    if wl and ip_allowed(client_ip(request), wl):
        return "whitelist"
    return None


def require_auth(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def require_host(host_id: int):
    host = db.get_host(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="host not found")
    return host


# ---------- version / self-update ----------
def ui_version():
    try:
        with open(os.path.join(ROOT, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def version_newer(latest, current):
    lt, ct = _ver_tuple(latest), _ver_tuple(current)
    return bool(lt) and lt > ct


_latest = {"tag": None, "at": 0.0}


async def latest_release():
    if _latest["tag"] and time.time() - _latest["at"] < 3600:
        return _latest["tag"]
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            r = await cl.get(f"https://api.github.com/repos/{REPO}/releases/latest")
            tag = r.json().get("tag_name")
    except Exception:
        tag = None
    if tag:
        _latest.update(tag=tag, at=time.time())
    return _latest["tag"]


def _spawn_update(unit, cmd):
    """Run a self-update outside our own service cgroup so the installer's
    `systemctl restart` doesn't kill it mid-run. ponytail: systemd-run needs the
    UI service to run as root (it does); setsid is a best-effort fallback."""
    try:
        subprocess.Popen(["systemd-run", "--collect", f"--unit={unit}", *cmd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        subprocess.Popen(f"setsid {' '.join(cmd)} >/tmp/{unit}.log 2>&1",
                         shell=True, start_new_session=True)


# ---------- app ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    _secret()
    task = asyncio.create_task(collector.poll_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


# ---------- auth routes ----------
@app.get("/api/me")
def me(request: Request):
    return {
        "needs_setup": db.get_setting("admin_user") is None,
        "authenticated": current_user(request) is not None,
        "user": current_user(request),
    }


@app.post("/api/setup")
async def setup(request: Request):
    if db.get_setting("admin_user") is not None:
        raise HTTPException(status_code=400, detail="already set up")
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or len(password) < 6:
        raise HTTPException(status_code=400, detail="username required, password min 6 chars")
    db.set_setting("admin_user", username)
    db.set_setting("admin_pw", hash_pw(password))
    db.set_setting("ip_whitelist", json.dumps(data.get("ip_whitelist") or []))
    resp = JSONResponse({"ok": True})
    resp.set_cookie("session", sign_session(username), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return resp


@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    user = db.get_setting("admin_user")
    if not user or data.get("username") != user or not check_pw(data.get("password") or "", db.get_setting("admin_pw") or ""):
        raise HTTPException(status_code=401, detail="invalid credentials")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("session", sign_session(user), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    return resp


@app.get("/api/settings")
def get_settings(user=Depends(require_auth)):
    return {"ip_whitelist": whitelist()}


@app.put("/api/settings")
async def put_settings(request: Request, user=Depends(require_auth)):
    data = await request.json()
    if "ip_whitelist" in data:
        db.set_setting("ip_whitelist", json.dumps(data["ip_whitelist"]))
    return {"ok": True}


# ---------- local site config (the only config the UI edits itself) ----------
@app.get("/api/config")
def get_config_local(user=Depends(require_auth)):
    return {"fields": uiconf.FIELDS, "values": uiconf.read(), "path": uiconf.CONF_PATH}


@app.put("/api/config")
async def put_config_local(request: Request, user=Depends(require_auth)):
    data = await request.json()
    updates = {k: v for k, v in (data.get("values") or {}).items() if k in uiconf.EDITABLE}
    try:
        values = uiconf.write(updates)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"cannot write {uiconf.CONF_PATH}: {e}")
    return {"ok": True, "values": values, "restart_required": True}


# ---------- version / self-update ----------
@app.get("/api/version")
async def version(user=Depends(require_auth)):
    cur = ui_version()
    latest = await latest_release()
    return {"ui": cur, "latest": latest, "update_available": version_newer(latest, cur)}


@app.post("/api/update/ui")
def update_ui(user=Depends(require_auth)):
    _spawn_update("sni-router-ui-update", ["/usr/local/bin/sni-router-ui", "-u"])
    return {"updating": True}


# ---------- discover a sni-router config on THIS host (Add Host convenience) ----------
# ponytail: regex parse of the api block — no YAML dep for two fields.
LOCAL_ROUTER_CONFIGS = ["/etc/sni-router/sni-router.yaml", "/etc/sni-router/sni-router.yml"]


def _yaml_block(text, key):
    m = re.search(rf"(?ms)^{key}:\s*\n(.*?)(?=^\S|\Z)", text)
    return m.group(1) if m else ""


def _yaml_field(block, key):
    m = re.search(rf'(?m)^\s+{key}:\s*["\']?([^"\'\n#]+)', block)
    return m.group(1).strip() if m else None


@app.get("/api/config/discover")
def discover_local_router(user=Depends(require_auth)):
    for path in LOCAL_ROUTER_CONFIGS:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        apib = _yaml_block(text, "api")
        bind = _yaml_field(apib, "bind") or ""
        host, _, port = bind.rpartition(":")
        if host in ("0.0.0.0", "", "::", "[::]"):
            host = "127.0.0.1"
        return {
            "found": True, "path": path, "ip": host,
            "port": int(port) if port.isdigit() else 9901,
            "token": _yaml_field(apib, "token") or "",
        }
    raise HTTPException(status_code=404, detail="no local sni-router config found "
                        f"(looked in {', '.join(LOCAL_ROUTER_CONFIGS)})")


# ---------- hosts ----------
def _host_public(h):
    return {"id": h["id"], "name": h["name"], "ip": h["ip"], "port": h["port"],
            "agent_port": h["agent_port"], "has_token": bool(h["token"]),
            "has_agent_token": bool(h["agent_token"])}


@app.get("/api/hosts")
def hosts(user=Depends(require_auth)):
    return [_host_public(h) for h in db.list_hosts()]


@app.post("/api/hosts")
async def create_host(request: Request, user=Depends(require_auth)):
    d = await request.json()
    if not d.get("name") or not d.get("ip") or not d.get("port"):
        raise HTTPException(status_code=400, detail="name, ip, port required")
    hid = db.add_host(d["name"], d["ip"], d["port"], d.get("token", ""),
                      d.get("agent_port", 9110), d.get("agent_token", ""))
    return _host_public(db.get_host(hid))


@app.put("/api/hosts/{host_id}")
async def edit_host(host_id: int, request: Request, user=Depends(require_auth)):
    require_host(host_id)
    d = await request.json()
    # only the keys actually sent are changed — a blank token field means "keep"
    fields = {k: d[k] for k in ("name", "ip", "port", "token", "agent_port", "agent_token")
              if k in d and d[k] is not None}
    db.update_host(host_id, **fields)
    return _host_public(db.get_host(host_id))


@app.post("/api/hosts/delete")
async def bulk_delete(request: Request, user=Depends(require_auth)):
    d = await request.json()
    db.delete_hosts([int(i) for i in d.get("ids", [])])
    return {"ok": True}


@app.delete("/api/hosts/{host_id}")
def delete_host(host_id: int, user=Depends(require_auth)):
    db.delete_hosts([host_id])
    return {"ok": True}


# ---------- remote provisioning over SSH ----------
def _require_ssh(data):
    ssh = data.get("ssh") or {}
    if not ssh.get("host"):
        raise HTTPException(status_code=400, detail="ssh.host required")
    if not ssh.get("password") and not ssh.get("key"):
        raise HTTPException(status_code=400, detail="ssh password or key required")
    return data


@app.post("/api/provision/agent")
async def provision_agent_ep(request: Request, user=Depends(require_auth)):
    data = _require_ssh(await request.json())
    try:
        return await asyncio.to_thread(provision.provision_agent, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/provision/sni-router")
async def provision_router_ep(request: Request, user=Depends(require_auth)):
    data = _require_ssh(await request.json())
    try:
        return await asyncio.to_thread(provision.provision_sni_router, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------- per-host admin proxy ----------
@app.get("/api/hosts/{host_id}/status")
async def host_status(host_id: int, user=Depends(require_auth)):
    host = require_host(host_id)
    try:
        r = await collector.admin_request(host, "GET", "/status", timeout=6)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"host unreachable: {e}")


@app.get("/api/hosts/{host_id}/config")
async def get_config(host_id: int, user=Depends(require_auth)):
    host = require_host(host_id)
    try:
        r = await collector.admin_request(host, "GET", "/config", timeout=6)
        return PlainTextResponse(r.text, status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"host unreachable: {e}")


def inject_api_token(text, token):
    """GET /config redacts api.token, so a round-tripped save would be rejected.
    The stored host token IS the router's api token — re-insert it under the
    api block unless the body already carries one. ponytail: block-style only;
    if a user hand-writes their own token: line we leave it untouched.
    """
    if not token or not re.search(r"(?m)^api:\s*$", text):
        return text
    block = re.search(r"(?ms)^api:\s*\n(.*?)(?=^\S|\Z)", text)
    if block and re.search(r"(?m)^\s+token:", block.group(1)):
        return text  # user supplied one
    return re.sub(r"(?m)^(api:\s*)$", rf'\1\n  token: "{token}"', text, count=1)


@app.put("/api/hosts/{host_id}/config")
async def put_config(host_id: int, request: Request, user=Depends(require_auth)):
    host = require_host(host_id)
    body = inject_api_token((await request.body()).decode("utf-8", "replace"), host["token"]).encode()
    try:
        r = await collector.admin_request(host, "PUT", "/config", content=body, timeout=20)
        # sni-router returns JSON on both success and validation error
        return Response(r.text, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"host unreachable: {e}")


# ---------- metrics agent (host CPU/RAM/net + IPs + version) ----------
@app.get("/api/hosts/{host_id}/agent")
async def host_agent(host_id: int, user=Depends(require_auth)):
    host = require_host(host_id)
    try:
        return await collector.fetch_agent(host)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"agent unreachable: {e}")


# declared before the {action} catch-all so it isn't swallowed as an "action"
@app.post("/api/hosts/{host_id}/agent-update")
async def host_agent_update(host_id: int, user=Depends(require_auth)):
    host = require_host(host_id)
    try:
        return await collector.agent_update(host)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"agent unreachable: {e}")


@app.post("/api/hosts/{host_id}/{action}")
async def control(host_id: int, action: str, user=Depends(require_auth)):
    if action not in ("reload", "restart"):
        raise HTTPException(status_code=404, detail="unknown action")
    host = require_host(host_id)
    try:
        r = await collector.admin_request(host, "POST", f"/{action}", timeout=30)
        return Response(r.text, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"host unreachable: {e}")


# ---------- metrics ----------
_RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "48h": 48 * 3600}


@app.get("/api/hosts/{host_id}/history")
def history(host_id: int, range: str = "1h", user=Depends(require_auth)):
    require_host(host_id)
    span = _RANGES.get(range, 3600)
    rows = db.history(host_id, int(time.time()) - span)
    return collector.build_history(rows)


@app.get("/api/hosts/{host_id}/live")
async def live(host_id: int, user=Depends(require_auth)):
    host = require_host(host_id)
    out = {"latest": db.latest(host_id), "status": None, "reachable": False}
    try:
        r = await collector.admin_request(host, "GET", "/status", timeout=6)
        if r.status_code == 200:
            out["status"] = r.json()
            out["reachable"] = True
    except Exception:
        pass
    return out


# ---------- static SPA (must be mounted last) ----------
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="spa")
