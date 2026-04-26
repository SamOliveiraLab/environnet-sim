#!/usr/bin/env bash
# Replace Ubuntu's old xpra 3.x with upstream xpra 6.x (modern HTML5 client).
# Run on the VM as ubuntu.
set -euo pipefail

echo "==> Stopping services"
sudo systemctl stop environnets-xpra || true

echo "==> Removing old xpra"
sudo apt-get remove -y xpra || true
sudo apt-get autoremove -y || true

echo "==> Adding upstream xpra repo (xpra.org)"
sudo install -d -m 0755 /usr/share/keyrings
curl -fsSL https://xpra.org/xpra.asc | sudo gpg --dearmor -o /usr/share/keyrings/xpra-archive-keyring.gpg

CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "deb [signed-by=/usr/share/keyrings/xpra-archive-keyring.gpg] https://xpra.org/ ${CODENAME} main" | \
    sudo tee /etc/apt/sources.list.d/xpra.list

sudo apt-get update

echo "==> Installing xpra 6.x"
sudo apt-get install -y xpra xpra-html5

echo "==> xpra version installed:"
xpra --version | head -3

echo "==> Restarting service"
sudo systemctl daemon-reload
sudo systemctl start environnets-xpra
sleep 6
systemctl --no-pager status environnets-xpra --lines=15 || true

echo
echo "==> Done. Test http://130.162.208.55 in your browser."
echo "    If WS still fails, check: sudo journalctl -u environnets-xpra -n 60"
