#!/usr/bin/env bash
# SNI-Router UI — site installer (the "control plane" half: the web app itself).
#
# Installs the FastAPI backend + built SPA + a local config file + a systemd unit.
#
#   -v, --version <ver>   GitHub tag to install (default: latest release, else main)
#   -s <IP:PORT>          bind address (default: 0.0.0.0 : random free port)
#   -h, --help
#
# The site uses login/password (created on first load) + an optional IP
# whitelist. It does NOT use a token — only the agents do.
set -euo pipefail

REPO="Ashteeer/SNI-Router-UI"
INSTALL_DIR="/opt/sni-router-ui"
DATA_DIR="$INSTALL_DIR/data"
CONF_DIR="/etc/sni-router-ui"
CONF="$CONF_DIR/ui.conf"
UNIT="/etc/systemd/system/sni-router-ui.service"

VERSION="" HOST="" PORT=""

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    -v|--version) VERSION="${2:-}"; shift 2 ;;
    -s)           S="${2:-}"; shift 2
                  case "$S" in
                    *:*) HOST="${S%:*}"; PORT="${S##*:}" ;;
                    *)   HOST="$S" ;;
                  esac ;;
    -h|--help)    sed -n '2,12p' "$0"; exit 0 ;;
    *)            die "unknown argument: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)."
for c in python3 curl tar; do command -v "$c" >/dev/null 2>&1 || die "$c is required."; done

rand_port() {
  local p
  for _ in $(seq 1 50); do
    p=$(( (RANDOM % 40000) + 20000 ))
    ss -ltnH 2>/dev/null | grep -q ":$p " || { echo "$p"; return; }
  done
  echo "$p"
}

resolve_ref() {
  case "${1:-}" in
    ""|latest)
      curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | grep -oE '"tag_name"[^,]*' | head -1 | sed -E 's/.*"([^"]+)".*/\1/' \
        | grep . || echo main ;;
    *) echo "$1" ;;
  esac
}

# Update/reinstall: keep the existing bind + DB path unless -s overrides them,
# so `sni-router-ui -u` doesn't move the port or the database out from under you.
DB_PATH=""
if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF" 2>/dev/null || true
  [ -n "$HOST" ] || HOST="${SNI_UI_HOST:-}"
  [ -n "$PORT" ] || PORT="${SNI_UI_PORT:-}"
  DB_PATH="${SNI_UI_DB:-}"
fi
[ -n "$DB_PATH" ] || DB_PATH="$DATA_DIR/sni-ui.db"

[ -n "$HOST" ] || HOST="0.0.0.0"
[ -n "$PORT" ] || PORT="$(rand_port)"
REF="$(resolve_ref "$VERSION")"

case "$REF" in
  main) TARBALL="https://github.com/$REPO/archive/refs/heads/main.tar.gz" ;;
  *)    TARBALL="https://github.com/$REPO/archive/refs/tags/$REF.tar.gz" ;;
esac

echo ">> downloading sni-router-ui ($REF)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$TARBALL" -o "$TMP/src.tgz" || die "download failed (check version/tag: $REF)"
install -d -m 0755 "$INSTALL_DIR" "$DATA_DIR" "$CONF_DIR"
tar -xzf "$TMP/src.tgz" -C "$INSTALL_DIR" --strip-components=1

echo ">> setting up Python backend"
python3 -m venv "$INSTALL_DIR/backend/.venv"
"$INSTALL_DIR/backend/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/backend/.venv/bin/pip" install -q -r "$INSTALL_DIR/backend/requirements.txt"

# Always rebuild when npm is present: the git tarball ships no dist/, so on an
# upgrade the OLD dist lingers — skipping the build would keep serving stale JS.
if command -v npm >/dev/null 2>&1; then
  echo ">> building frontend (npm)"
  rm -rf "$INSTALL_DIR/frontend/dist"
  ( cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund --silent && npm run build --silent )
elif [ ! -d "$INSTALL_DIR/frontend/dist" ]; then
  die "frontend not built and npm not found. Install Node 18+ and re-run, or build frontend/dist elsewhere and copy it to $INSTALL_DIR/frontend/dist"
fi

umask 022
cat > "$CONF" <<EOF
# SNI-Router UI site config — written by install-site.sh
SNI_UI_HOST=$HOST
SNI_UI_PORT=$PORT
SNI_UI_DB=$DB_PATH
EOF

if command -v systemctl >/dev/null 2>&1; then
  cat > "$UNIT" <<EOF
[Unit]
Description=SNI-Router UI backend
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR/backend
EnvironmentFile=$CONF
ExecStart=$INSTALL_DIR/backend/.venv/bin/uvicorn app:app --host \${SNI_UI_HOST} --port \${SNI_UI_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable sni-router-ui.service
  # restart (not just enable --now): on an upgrade the unit is already running, and
  # `--now` would NOT reload the new backend code. restart always picks it up.
  systemctl restart sni-router-ui.service
  sleep 1
  systemctl is-active --quiet sni-router-ui.service || die "service failed to start (journalctl -u sni-router-ui)"
else
  echo "!! systemd not found — run manually:"
  echo "   cd $INSTALL_DIR/backend && SNI_UI_CONF=$CONF .venv/bin/uvicorn app:app --host $HOST --port $PORT"
fi

# CLI: `sni-router-ui -u|--update  -v|--version  -h|--help`
install -d -m 0755 /usr/local/bin
cat > /usr/local/bin/sni-router-ui <<'WRAP'
#!/usr/bin/env bash
REPO="Ashteeer/SNI-Router-UI"
case "${1:-}" in
  -v|--version) cat /opt/sni-router-ui/VERSION 2>/dev/null || echo unknown ;;
  -u|--update)  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/scripts/install-site.sh" | bash -s -- "${@:2}" ;;
  -h|--help|"") printf '%s\n' "sni-router-ui — web UI control" \
                  "  -u, --update    update to the latest release (keeps bind + database)" \
                  "  -v, --version   print installed version" \
                  "  -h, --help      show this help" ;;
  *) echo "unknown option: $1" >&2; exit 1 ;;
esac
WRAP
chmod 0755 /usr/local/bin/sni-router-ui

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$HOST_IP" ] || HOST_IP="<host-ip>"
SHOW_IP="$HOST"; [ "$HOST" = "0.0.0.0" ] && SHOW_IP="$HOST_IP"

cat <<EOF

============================================================
  SNI-Router UI installed and running.

    URL   http://${SHOW_IP}:${PORT}

  Open it and complete the one-time setup (admin login +
  optional IP whitelist). Put TLS in front for production.
============================================================
EOF
