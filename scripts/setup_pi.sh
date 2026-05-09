#!/usr/bin/env bash
# One-shot provisioning for a fresh Raspberry Pi OS Lite install.
# Idempotent: safe to re-run.
#
# This sets up the device side of the kit. After this completes, run
# `scripts/image_setup.sh` once to pair the OBD adapter and configure rclone,
# then bake the SD card image for distribution.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/5] apt packages"
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv \
    bluetooth bluez bluez-tools \
    gpsd gpsd-clients python3-gps \
    i2c-tools \
    rclone \
    network-manager

echo "[2/5] enable I2C and serial UART"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_serial 2

echo "[3/5] python deps"
python3 -m pip install --upgrade pip
python3 -m pip install -r "$REPO_DIR/requirements.txt"

echo "[4/5] gpsd default device"
sudo sed -i 's|^DEVICES=.*|DEVICES="/dev/ttyAMA0"|' /etc/default/gpsd
sudo sed -i 's|^GPSD_OPTIONS=.*|GPSD_OPTIONS="-n"|' /etc/default/gpsd
sudo systemctl enable --now gpsd

echo "[5/5] install systemd units"
sudo cp "$REPO_DIR"/systemd/*.service /etc/systemd/system/
sudo cp "$REPO_DIR"/systemd/*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable obd-ev-firstboot.service
sudo systemctl enable obd-ev-pair.service
sudo systemctl enable obd-ev.service
sudo systemctl enable obd-ev-upload.timer

# Default env file (overridable per-device).
if [ ! -f /etc/default/obd-ev ]; then
    sudo tee /etc/default/obd-ev >/dev/null <<EOF
OBD_EV_LOG_DIR=$REPO_DIR/logs
OBD_EV_REMOTE=obd-ev:obd-ev-uploads
OBD_EV_RCLONE_CONF=/home/pi/.config/rclone/rclone.conf
EOF
fi

echo "Done. Next: scripts/image_setup.sh (pair OBD, configure rclone)."
