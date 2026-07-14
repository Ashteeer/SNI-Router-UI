"""SQLite storage: settings, hosts, and the rolling metrics time-series.

ponytail: one global lock; writes are tiny and infrequent (poller every 5s).
Swap for a connection pool only if throughput ever demands it.
"""
import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("SNI_UI_DB", os.path.join(os.path.dirname(__file__), "sni-ui.db"))
RETENTION_SECS = 2 * 86400  # dashboard shows at most 2 days

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS hosts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                token TEXT DEFAULT '',
                agent_port INTEGER DEFAULT 9110,
                agent_token TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metrics(
                host_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                cpu_pct REAL, mem_used INTEGER, mem_total INTEGER,
                disk_used INTEGER, disk_total INTEGER,
                net_rx INTEGER, net_tx INTEGER,
                conns_active INTEGER, conns_total INTEGER,
                bytes_up INTEGER, bytes_down INTEGER,
                up INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_metrics ON metrics(host_id, ts);
            """
        )
        # migrate: sni-router unified admin+metrics into one api port (config.md §8),
        # so the separate metrics_port column is gone. Drop it if an older DB has it.
        # ponytail: needs SQLite ≥3.35 (Ubuntu 24.04 = 3.45); ignore if unsupported.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(hosts)").fetchall()}
        if "metrics_port" in cols:
            try:
                c.execute("ALTER TABLE hosts DROP COLUMN metrics_port")
            except sqlite3.OperationalError:
                pass
        # agent may use a different token than the router api (blank = same token)
        if "agent_token" not in cols:
            c.execute("ALTER TABLE hosts ADD COLUMN agent_token TEXT DEFAULT ''")


# ---- settings ----
def get_setting(key, default=None):
    with _lock, _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---- hosts ----
def list_hosts():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM hosts ORDER BY id").fetchall()]


def get_host(host_id):
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
    return dict(row) if row else None


def add_host(name, ip, port, token="", agent_port=9110, agent_token=""):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO hosts(name,ip,port,token,agent_port,agent_token,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (name, ip, int(port), token, int(agent_port), agent_token, int(time.time())),
        )
        return cur.lastrowid


def update_host(host_id, **fields):
    """Update the given columns of a host. Only known columns are applied."""
    allowed = ("name", "ip", "port", "token", "agent_port", "agent_token")
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    with _lock, _conn() as c:
        c.execute(f"UPDATE hosts SET {cols} WHERE id=?", [*sets.values(), host_id])


def delete_hosts(ids):
    if not ids:
        return
    qs = ",".join("?" * len(ids))
    with _lock, _conn() as c:
        c.execute(f"DELETE FROM hosts WHERE id IN ({qs})", ids)
        c.execute(f"DELETE FROM metrics WHERE host_id IN ({qs})", ids)


# ---- metrics ----
_METRIC_COLS = (
    "cpu_pct mem_used mem_total disk_used disk_total "
    "net_rx net_tx conns_active conns_total bytes_up bytes_down up"
).split()


def insert_metric(host_id, ts, values):
    cols = ["host_id", "ts"] + _METRIC_COLS
    row = [host_id, ts] + [values.get(k) for k in _METRIC_COLS]
    with _lock, _conn() as c:
        c.execute(
            f"INSERT INTO metrics({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            row,
        )


def history(host_id, since_ts):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM metrics WHERE host_id=? AND ts>=? ORDER BY ts",
            (host_id, since_ts),
        ).fetchall()
    return [dict(r) for r in rows]


def latest(host_id):
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM metrics WHERE host_id=? ORDER BY ts DESC LIMIT 1", (host_id,)
        ).fetchone()
    return dict(row) if row else None


def prune(before_ts):
    with _lock, _conn() as c:
        c.execute("DELETE FROM metrics WHERE ts<?", (before_ts,))
