#!/usr/bin/env bash
# Pull latest, sync infra files if changed, restart sandbox service.
# Idempotent. Run on the VM (or by GitHub Actions over SSH).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/environnet-sim}"
cd "$APP_DIR"

git fetch --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo "Already up to date ($LOCAL)"
    # Still allow forced restart with --force
    if [[ "${1:-}" != "--force" ]]; then
        exit 0
    fi
fi

echo "==> Pulling $LOCAL -> $REMOTE"
git pull --ff-only

source .venv/bin/activate
pip install -e ".[desktop]" --quiet --no-cache-dir || \
    pip install -e ".[desktop]" --no-cache-dir

# Sync systemd unit if changed
if ! sudo diff -q deploy/environnets-xpra.service /etc/systemd/system/environnets-xpra.service >/dev/null 2>&1; then
    echo "==> systemd unit changed, updating"
    sudo cp deploy/environnets-xpra.service /etc/systemd/system/environnets-xpra.service
    sudo systemctl daemon-reload
fi

# Sync Caddyfile if changed
if ! sudo diff -q deploy/Caddyfile.prod /etc/caddy/Caddyfile >/dev/null 2>&1; then
    echo "==> Caddyfile changed, updating + reloading Caddy"
    sudo cp deploy/Caddyfile.prod /etc/caddy/Caddyfile
    sudo systemctl reload caddy
fi

# Restart sandbox so it picks up new code
echo "==> Restarting environnets-xpra"
sudo systemctl restart environnets-xpra
sleep 4
systemctl --no-pager status environnets-xpra --lines=3
echo "==> Deploy complete."
