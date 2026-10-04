#!/usr/bin/env bash
# One-command deploy of the Backfill dashboard to an Ubuntu server (tested on Vultr, Ubuntu 22.04).
#
#   scripts/deploy_vultr.sh root@SERVER_IP [ENV_FILE] [DOMAIN]
#
# ENV_FILE defaults to ~/.config/backfill/server.env: the ONE .env for the server, holding only
# read-only Tiger/Snowflake logins and Webull keys (no admin logins, no Gemini key). It is copied
# to /opt/backfill/app/.env (mode 600, owner backfill) and never committed or printed.
#
# DOMAIN defaults to the free sslip.io name for the IP (155.138.224.207 -> 155-138-224-207.sslip.io).
# Caddy serves it over HTTPS with an automatic Let's Encrypt certificate and redirects HTTP to it.
# If no certificate can be obtained, Caddy falls back to plain HTTP so the site stays up.
#
# The dashboard itself runs as an unprivileged "backfill" user on 127.0.0.1:8080 (systemd,
# auto-restart), reachable only through Caddy. Safe to re-run: pulls latest main and restarts.
set -euo pipefail

TARGET="${1:?usage: scripts/deploy_vultr.sh root@SERVER_IP [ENV_FILE] [DOMAIN]}"
ENV_FILE="${2:-$HOME/.config/backfill/server.env}"
HOST="${TARGET#*@}"
DOMAIN="${3:-${HOST//./-}.sslip.io}"
REPO="https://github.com/AIForge10/BackFill.git"

[ -f "$ENV_FILE" ] || { echo "Env file not found: $ENV_FILE" >&2; exit 1; }
for name in TIGER_DATABASE_URL SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_PASSWORD; do
  grep -q "^$name=." "$ENV_FILE" || { echo "$ENV_FILE is missing $name" >&2; exit 1; }
done
if grep -qE "^(TIGER_INGEST_DATABASE_URL|GEMINI_API_KEY)=." "$ENV_FILE"; then
  echo "Refusing: $ENV_FILE contains writer or Gemini credentials; the public server must not have them." >&2
  exit 1
fi

echo "==> Uploading the server .env (contents not shown)"
scp -q -o StrictHostKeyChecking=accept-new "$ENV_FILE" "$TARGET:/root/backfill.env.upload"

echo "==> Configuring $HOST (HTTPS name: $DOMAIN)"
ssh -o StrictHostKeyChecking=accept-new "$TARGET" REPO="$REPO" DOMAIN="$DOMAIN" HOST_IP="$HOST" bash -s <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
APP=/opt/backfill/app

apt-get update -qq
apt-get install -y -qq git curl ufw debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null

# Unprivileged service user; uv installed system-wide.
id backfill >/dev/null 2>&1 || useradd --system --home /opt/backfill --create-home --shell /usr/sbin/nologin backfill
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null

# Caddy (official package) for HTTPS in front of the app.
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

# Latest main plus tags (Verify now needs the freeze-v1 tag).
if [ -d "$APP/.git" ]; then
  sudo -u backfill git -C "$APP" fetch -q --tags origin
  sudo -u backfill git -C "$APP" checkout -q main
  sudo -u backfill git -C "$APP" reset -q --hard origin/main
else
  sudo -u backfill git clone -q "$REPO" "$APP"
  sudo -u backfill git -C "$APP" fetch -q --tags
fi

# The one server .env: read-only logins, owner-only.
install -o backfill -g backfill -m 600 /root/backfill.env.upload "$APP/.env"
rm -f /root/backfill.env.upload

# Python 3.12 + locked dependencies (dashboard = Tiger driver, snowflake = audit connector).
cd "$APP"
sudo -u backfill env HOME=/opt/backfill UV_PYTHON_INSTALL_DIR=/opt/backfill/python \
  /usr/local/bin/uv sync -q --frozen --extra dashboard --extra snowflake

# The app listens on localhost only; Caddy is the only public entry point.
cat > /etc/systemd/system/backfill-dashboard.service <<UNIT
[Unit]
Description=Backfill observatory dashboard (read-only)
After=network-online.target
Wants=network-online.target

[Service]
User=backfill
Group=backfill
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python -m dashboard.server --host 127.0.0.1 --port 8080
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q backfill-dashboard
systemctl restart backfill-dashboard
for i in $(seq 1 20); do curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && break; sleep 1; done

ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# HTTPS on the hostname; the bare IP over HTTP redirects to it.
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	encode gzip
	header Strict-Transport-Security "max-age=86400"
	reverse_proxy 127.0.0.1:8080
}
http://$HOST_IP {
	redir https://$DOMAIN{uri} permanent
}
CADDY
systemctl enable -q caddy
systemctl restart caddy

tls_ok=no
for i in $(seq 1 45); do
  if curl -fsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health" >/dev/null 2>&1; then tls_ok=yes; break; fi
  sleep 2
done
if [ "$tls_ok" = yes ]; then
  echo "https: certificate issued for $DOMAIN"
else
  # Never leave the site down: serve plain HTTP if the certificate could not be obtained.
  echo "https: certificate NOT obtained (rate limit or DNS); falling back to plain HTTP"
  printf ':80 {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8080\n}\n' > /etc/caddy/Caddyfile
  systemctl reload caddy
fi

systemctl is-active --quiet backfill-dashboard && echo "service: running" || { journalctl -u backfill-dashboard -n 30 --no-pager; exit 1; }
echo "commit: $(sudo -u backfill git -C "$APP" log --oneline -1)"
REMOTE

URL="https://$DOMAIN"
curl -fsS --max-time 15 "$URL/api/health" >/dev/null 2>&1 || URL="http://$HOST"
echo "==> Checking $URL from here"
curl -fsS "$URL/api/health" >/dev/null && echo "health: ok"
curl -fsS "$URL/api/live" | python3 -c 'import json,sys; print("tiger live panel:", json.load(sys.stdin)["state"])'
curl -fsS "$URL/api/audit/variants" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("research audit source:", d["source"])'
curl -fsS "$URL/api/fda/range" | python3 -c 'import json,sys; print("time machine:", json.load(sys.stdin)["state"])'
curl -fsS "$URL/api/proof/verify" | python3 -c 'import json,sys; print("solana verify:", json.load(sys.stdin)["status"])'
curl -fsS "$URL/api/prices/specialists" | python3 -c 'import json,sys; print("webull chart:", json.load(sys.stdin)["state"])'
echo "==> Live at $URL"
