#!/usr/bin/env bash
# SNI-Router UI — agent installer (the "data plane" half: host CPU/RAM/disk/net).
#
# Installs agent.py + a local config file + a systemd unit on a managed host.
#
#   -v, --version <ver>   GitHub tag to install (default: latest release, else main)
#   -a <IP:PORT>          bind address (default: 0.0.0.0 : random free port)
#   -t, --token <token>   bearer token (default: auto-generated)
#   --purge               clean install: wipe any existing agent dir/config first
#   -h, --help
#
# Prints  IP:PORT  and  token  at the end — paste them into the UI's Add Host
# form, or let the UI run this for you over SSH (Hosts → Remote install).
set -euo pipefail

REPO="Ashteeer/SNI-Router-UI"
INSTALL_DIR="/opt/sni-router-agent"
CONF_DIR="/etc/sni-router-agent"
CONF="$CONF_DIR/agent.conf"
UNIT="/etc/systemd/system/sni-router-agent.service"

VERSION="" BIND="" PORT="" TOKEN="" PURGE=""

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    -v|--version) VERSION="${2:-}"; shift 2 ;;
    -a)           A="${2:-}"; shift 2
                  case "$A" in
                    *:*) BIND="${A%:*}"; PORT="${A##*:}" ;;
                    *)   BIND="$A" ;;
                  esac ;;
    -t|--token)   TOKEN="${2:-}"; shift 2 ;;
    --purge)      PURGE=1; shift ;;
    -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
    *)            die "unknown argument: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)."
command -v python3 >/dev/null 2>&1 || die "python3 is required."
command -v curl    >/dev/null 2>&1 || die "curl is required."

# --purge = clean install: tear down any existing agent so nothing old lingers.
# (In-dashboard version updates run WITHOUT --purge and keep token/bind/port.)
if [ -n "$PURGE" ]; then
  echo ">> clean install: removing existing agent (dir, config, unit)"
  systemctl disable --now sni-router-agent.service >/dev/null 2>&1 || true
  rm -f "$UNIT"
  command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload >/dev/null 2>&1 || true
  rm -rf "$INSTALL_DIR" "$CONF_DIR"
fi

gen_token() { openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

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

# Update/reinstall: keep the existing token/bind/port unless overridden on the CLI,
# so `sni-router-agent -u` never breaks the host row already saved in the UI.
if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF" 2>/dev/null || true
  [ -n "$TOKEN" ] || TOKEN="${SNI_AGENT_TOKEN:-}"
  [ -n "$BIND" ]  || BIND="${SNI_AGENT_BIND:-}"
  [ -n "$PORT" ]  || PORT="${SNI_AGENT_PORT:-}"
fi

[ -n "$BIND" ]  || BIND="0.0.0.0"
[ -n "$PORT" ]  || PORT="$(rand_port)"
[ -n "$TOKEN" ] || TOKEN="$(gen_token)"
REF="$(resolve_ref "$VERSION")"

echo ">> installing sni-router agent ($REF) -> $INSTALL_DIR"
install -d -m 0755 "$INSTALL_DIR" "$CONF_DIR"
curl -fsSL "https://raw.githubusercontent.com/$REPO/$REF/agent/agent.py" -o "$INSTALL_DIR/agent.py" \
  || die "download failed (check version/tag: $REF)"
# Keep the agent's reported version in lockstep with the release VERSION file, so
# a self-update always bumps AGENT_VERSION even if agent.py's literal lagged behind
# (that gap once made "update available" stick forever — the version never moved).
VER="$(curl -fsSL "https://raw.githubusercontent.com/$REPO/$REF/VERSION" 2>/dev/null | tr -d '[:space:]')"
[ -n "$VER" ] && sed -i "s/^AGENT_VERSION = .*/AGENT_VERSION = \"$VER\"/" "$INSTALL_DIR/agent.py" || true
chmod 0755 "$INSTALL_DIR/agent.py"

umask 077
cat > "$CONF" <<EOF
# SNI-Router UI agent config — written by install-agent.sh
SNI_AGENT_TOKEN=$TOKEN
SNI_AGENT_BIND=$BIND
SNI_AGENT_PORT=$PORT
EOF

if command -v systemctl >/dev/null 2>&1; then
  cat > "$UNIT" <<EOF
[Unit]
Description=SNI-Router UI metrics agent
After=network.target

[Service]
EnvironmentFile=$CONF
ExecStart=/usr/bin/python3 $INSTALL_DIR/agent.py
Restart=on-failure
RestartSec=3
# Runs as root (no sandboxing): the agent's POST /update self-updates by running
# the installer + systemctl, which needs root. Guard it with a strong token.
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable sni-router-agent.service
  # restart (not just enable --now): on a reinstall the unit is already running, and
  # `--now` would NOT apply the new config/code. restart always picks it up.
  systemctl restart sni-router-agent.service
  sleep 1
  systemctl is-active --quiet sni-router-agent.service || die "service failed to start (journalctl -u sni-router-agent)"
else
  echo "!! systemd not found — run manually:"
  echo "   SNI_AGENT_CONF=$CONF python3 $INSTALL_DIR/agent.py"
fi

# CLI: `sni-router-agent -u|--update  -v|--version  -h|--help`
install -d -m 0755 /usr/local/bin
cat > /usr/local/bin/sni-router-agent <<'WRAP'
#!/usr/bin/env bash
REPO="Ashteeer/SNI-Router-UI"
case "${1:-}" in
  -v|--version) python3 /opt/sni-router-agent/agent.py version 2>/dev/null || echo unknown ;;
  -u|--update)  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/scripts/install-agent.sh" | bash -s -- "${@:2}" ;;
  -h|--help|"") printf '%s\n' "sni-router-agent — metrics agent control" \
                  "  -u, --update    update to the latest release (keeps token/port)" \
                  "  -v, --version   print installed version" \
                  "  -h, --help      show this help" ;;
  *) echo "unknown option: $1" >&2; exit 1 ;;
esac
WRAP
chmod 0755 /usr/local/bin/sni-router-agent

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$HOST_IP" ] || HOST_IP="<host-ip>"
SHOW_IP="$BIND"; [ "$BIND" = "0.0.0.0" ] && SHOW_IP="$HOST_IP"

cat <<EOF

============================================================
  SNI-Router agent installed and running.
  Add this host in the UI (Hosts → Add Host), Agent fields:

    IP:PORT   ${SHOW_IP}:${PORT}
    token     ${TOKEN}
============================================================
EOF
