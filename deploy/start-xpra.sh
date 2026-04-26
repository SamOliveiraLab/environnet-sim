#!/usr/bin/env bash
# Start xpra serving the EnvironNets desktop app on display :100,
# with HTML5 client over TCP 14500.  Called by systemd.
set -euo pipefail

VENV_PY="$HOME/environnet-sim/.venv/bin/python"

# Note: we do NOT pre-stop a previous session here -- xpra v6 with
# `--use-display=auto` handles that, and an explicit pre-stop hangs
# for ~20s when there's no session to stop, fighting with systemd.

exec /usr/bin/xpra start :100 \
    --bind-tcp=127.0.0.1:14500 \
    --html=on \
    --sharing=yes \
    --daemon=no \
    --use-display=auto \
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
