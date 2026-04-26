#!/usr/bin/env bash
# One-time setup for the Oracle Ubuntu VM hosting the sandbox.
# Run on the VM as the `ubuntu` user.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/SamOliveiraLab/environnet-sim.git}"
APP_DIR="${APP_DIR:-$HOME/environnet-sim}"

echo "==> Cloning repo to $APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
    git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git pull --ff-only

echo "==> Creating virtualenv"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[web]"

echo "==> Installing systemd unit"
sudo cp deploy/environnets-web.service /etc/systemd/system/environnets-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now environnets-web

echo "==> Installing Caddy config"
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy

echo "==> Done. Service status:"
systemctl --no-pager status environnets-web --lines=5 || true
