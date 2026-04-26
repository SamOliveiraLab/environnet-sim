#!/usr/bin/env bash
# Install xpra (display server + HTML5 client) and PyQt6 runtime deps
# on the Oracle Ubuntu 24.04 VM.  Run on the VM as `ubuntu`.
set -euo pipefail

echo "==> Installing xpra and X11 runtime deps"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    xpra xvfb \
    libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
    libegl1 libdbus-1-3 libfontconfig1 libxrender1 \
    libxi6 libxrandr2 libxss1 libxtst6 \
    libgl1 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-sync1 libxcb-util1 libxcb-xfixes0 \
    libxcb-xkb1 libxkbcommon0 \
    fonts-dejavu-core

echo "==> Installing PyQt6 desktop extras"
cd "$HOME/environnet-sim"
source .venv/bin/activate
pip install -e ".[desktop]" --no-cache-dir

echo "==> Sanity check: PyQt6 imports"
python -c "from PyQt6.QtWidgets import QApplication; print('PyQt6 OK')"

echo "==> Installed."
