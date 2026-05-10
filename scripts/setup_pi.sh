#!/usr/bin/env bash
# One-shot provisioning for a fresh Raspberry Pi OS Lite install.
# Idempotent: safe to re-run.
#
# This sets up the device side of the kit. After this completes, run
# `scripts/image_setup.sh` once to configure rclone, then bake the SD card
# image for distribution.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
VENV_DIR="$REPO_DIR/.venv"

echo "[1/5] apt packages"
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv \
    bluetooth bluez \
    gpsd gpsd-clients python3-gps \
    i2c-tools \
    rclone \
    network-manager

echo "[2/5] enable I2C and GPS UART"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_serial 2

echo "[3/5] python deps"
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/requirements.txt"

echo "[4/5] gpsd default device"
sudo sed -i 's|^DEVICES=.*|DEVICES="/dev/ttyAMA0"|' /etc/default/gpsd
sudo sed -i 's|^GPSD_OPTIONS=.*|GPSD_OPTIONS="-n"|' /etc/default/gpsd
sudo systemctl enable --now gpsd

echo "[5/5] install systemd units"
tmp_units="$(mktemp -d)"
cp "$REPO_DIR"/systemd/*.service "$tmp_units"/
cp "$REPO_DIR"/systemd/*.timer "$tmp_units"/
sed -i \
    -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@VENV_DIR@|$VENV_DIR|g" \
    -e "s|@INSTALL_USER@|$INSTALL_USER|g" \
    "$tmp_units"/*.service
sudo cp "$tmp_units"/*.service /etc/systemd/system/
sudo cp "$tmp_units"/*.timer   /etc/systemd/system/
rm -rf "$tmp_units"
sudo systemctl daemon-reload
sudo systemctl enable obd-ev-firstboot.service
sudo systemctl enable obd-ev.service
sudo systemctl enable obd-ev-upload.timer

# Default env file (overridable per-device).
if [ ! -f /etc/default/obd-ev ]; then
    sudo tee /etc/default/obd-ev >/dev/null <<EOF
OBD_EV_LOG_DIR=$REPO_DIR/logs
OBD_EV_REMOTE=obd-ev:obd-ev-uploads
OBD_EV_RCLONE_CONF=$INSTALL_HOME/.config/rclone/rclone.conf
EOF
fi

echo "Done. Next: scripts/image_setup.sh (configure rclone)."
