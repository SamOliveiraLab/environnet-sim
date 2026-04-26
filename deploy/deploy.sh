#!/usr/bin/env bash
# Pull latest, reinstall deps if needed, restart sandbox service.
# Idempotent. Run on the VM.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/environnet-sim}"
cd "$APP_DIR"

git fetch --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo "Already up to date ($LOCAL)"
    exit 0
fi

echo "==> Pulling $LOCAL -> $REMOTE"
git pull --ff-only

source .venv/bin/activate
pip install -e ".[web]" --quiet

sudo systemctl restart environnets-web
echo "==> Restarted. Status:"
systemctl --no-pager status environnets-web --lines=3
