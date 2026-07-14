"""Local site config file — the ONLY config the web UI edits itself.

Plain KEY=VALUE (systemd EnvironmentFile-compatible). Path from SNI_UI_CONF,
default /etc/sni-router-ui/ui.conf. On import we fold the file into os.environ
(without overriding real env vars) so db.py / uvicorn pick the values up.

Editable-from-UI keys are whitelisted in EDITABLE; a PUT only touches those.
Changing host/port needs a service restart (uvicorn binds once at boot) — the
UI says so. ponytail: no yaml dep, no schema lib; it's three strings.
"""
import os

CONF_PATH = os.environ.get("SNI_UI_CONF", "/etc/sni-router-ui/ui.conf")

# keys the web UI may read and write, with their fallback defaults
DEFAULTS = {
    "SNI_UI_HOST": "127.0.0.1",
    "SNI_UI_PORT": "8899",
    "SNI_UI_DB": "",
}
EDITABLE = tuple(DEFAULTS)

# metadata for the Settings form (label + whether a restart is required)
FIELDS = [
    {"key": "SNI_UI_HOST", "label": "Listen IP", "restart": True,
     "hint": "0.0.0.0 = all interfaces. Restart required."},
    {"key": "SNI_UI_PORT", "label": "Listen port", "restart": True,
     "hint": "TCP port the UI serves on. Restart required."},
    {"key": "SNI_UI_DB", "label": "Database path", "restart": True,
     "hint": "SQLite file path. Leave blank for the default next to the app."},
]


def _parse(path):
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


def load():
    """Fold file values into the environment as defaults (real env wins)."""
    for k, v in _parse(CONF_PATH).items():
        os.environ.setdefault(k, v)


def read():
    """Current editable settings: file value, else env, else built-in default."""
    conf = _parse(CONF_PATH)
    return {k: conf.get(k, os.environ.get(k, DEFAULTS[k])) for k in EDITABLE}


def write(updates):
    """Merge whitelisted updates into the file. Raises OSError if not writable."""
    conf = _parse(CONF_PATH)
    for k, v in updates.items():
        if k in EDITABLE:
            conf[k] = str(v)
    os.makedirs(os.path.dirname(CONF_PATH) or ".", exist_ok=True)
    body = "".join(f"{k}={conf[k]}\n" for k in conf)
    with open(CONF_PATH, "w") as f:
        f.write(body)
    return read()


# apply on import, before db.py reads the environment
load()
