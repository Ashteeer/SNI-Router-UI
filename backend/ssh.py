"""Thin paramiko wrapper for remote provisioning (install agent / sni-router).

Credentials are used transiently for a single connection and are NEVER stored —
the provisioning endpoints take them per request and drop them when done.

All calls here are blocking; the endpoints run them via asyncio.to_thread so the
event loop isn't held. ponytail: no connection pool, no retries — provisioning is
a one-shot, human-triggered action.
"""
import io

import paramiko


def _load_key(text):
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except Exception:
            continue
    raise ValueError("unsupported or invalid private key")


def connect(host, port=22, user="root", password=None, key=None, timeout=15):
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = _load_key(key) if key else None
    cl.connect(
        hostname=host, port=int(port or 22), username=user,
        password=password or None, pkey=pkey, timeout=timeout,
        allow_agent=False, look_for_keys=False,
    )
    return cl


def run(cl, cmd, timeout=300):
    """Run a command; return (exit_code, combined_output)."""
    _, out, err = cl.exec_command(cmd, timeout=timeout)
    stdout = out.read().decode("utf-8", "replace")
    stderr = err.read().decode("utf-8", "replace")
    code = out.channel.recv_exit_status()
    return code, (stdout + stderr)


def put(cl, remote_path, data):
    """Upload text to a user-writable path (e.g. /tmp)."""
    sftp = cl.open_sftp()
    try:
        with sftp.open(remote_path, "w") as f:
            f.write(data)
    finally:
        sftp.close()


def put_root(cl, sudo, remote_path, data, mode="0644"):
    """Upload text to a root-owned path via /tmp + `install` (works for non-root
    users with passwordless sudo, and for root where sudo is empty)."""
    tmp = "/tmp/.sni-prov-" + remote_path.replace("/", "_")
    sftp = cl.open_sftp()
    try:
        with sftp.open(tmp, "w") as f:
            f.write(data)
    finally:
        sftp.close()
    code, log = run(cl, f"{sudo}install -D -m {mode} {tmp} {remote_path} && rm -f {tmp}")
    if code != 0:
        raise RuntimeError(f"writing {remote_path} failed: {log.strip()}")
