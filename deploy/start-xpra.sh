#!/usr/bin/env bash
# Start xpra serving the EnvironNets desktop app on display :100,
# with HTML5 client over TCP 14500.  Called by systemd.
set -euo pipefail

VENV_PY="$HOME/environnet-sim/.venv/bin/python"

# Cleanup any stale xpra session on :100 from a prior run
/usr/bin/xpra stop :100 >/dev/null 2>&1 || true
sleep 1

exec /usr/bin/xpra start :100 \
    --bind-tcp=127.0.0.1:14500 \
    --html=on \
    --daemon=no \
    --start-child="$VENV_PY -m environnets" \
    --exit-with-children=yes \
    --notifications=no \
    --bell=no \
    --webcam=no \
    --pulseaudio=no \
    --speaker=disabled \
    --microphone=disabled \
    --mdns=no \
    --systemd-run=no \
    --start-new-commands=no \
    --resize-display=1280x800
