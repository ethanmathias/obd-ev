#!/usr/bin/env bash
# One-shot provisioning for a fresh Raspberry Pi OS Lite install.
# Idempotent: safe to re-run.
set -euo pipefail

echo "[1/4] apt packages"
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv \
    bluetooth bluez bluez-tools \
    gpsd gpsd-clients python3-gps \
    i2c-tools

echo "[2/4] enable I2C and serial UART"
sudo raspi-config nonint do_i2c 0      # enable I2C
sudo raspi-config nonint do_serial 2   # enable hw uart, disable login shell

echo "[3/4] python deps"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "[4/4] gpsd default device"
# Point gpsd at the Pi UART. Adjust if you use a USB GPS instead.
sudo sed -i 's|^DEVICES=.*|DEVICES="/dev/ttyAMA0"|' /etc/default/gpsd
sudo sed -i 's|^GPSD_OPTIONS=.*|GPSD_OPTIONS="-n"|' /etc/default/gpsd
sudo systemctl enable --now gpsd

echo "Done. Reboot recommended."
