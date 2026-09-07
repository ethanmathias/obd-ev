#!/usr/bin/env bash
# System provisioning for a fresh Raspberry Pi OS Lite install: packages,
# interfaces, virtualenv, services. Idempotent, safe to re-run.
#
# You normally do not run this directly. `scripts/setup_kit.sh` calls it as
# one step of building a kit, and also handles the kit id, vehicle, cloud
# upload and verification. Run this alone only to repair those parts of an
# existing card.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
VENV_DIR="$REPO_DIR/.venv"

echo "[1/8] apt packages"
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv \
    bluetooth bluez \
    gpsd gpsd-clients python3-gps \
    i2c-tools \
    rclone \
    network-manager \
    dnsmasq-base

echo "[2/8] enable I2C and GPS UART"
sudo raspi-config nonint do_i2c 0
# do_serial was split in newer raspi-config; fall back for older images.
if sudo raspi-config nonint do_serial_hw 0 2>/dev/null; then
    sudo raspi-config nonint do_serial_cons 1
else
    sudo raspi-config nonint do_serial 2
fi

echo "[3/8] python deps"
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/requirements.txt"

echo "[4/8] gpsd default device"
sudo sed -i 's|^DEVICES=.*|DEVICES="/dev/ttyAMA0"|' /etc/default/gpsd
sudo sed -i 's|^GPSD_OPTIONS=.*|GPSD_OPTIONS="-n"|' /etc/default/gpsd
sudo systemctl enable --now gpsd

echo "[5/8] state directory"
sudo mkdir -p /var/lib/obd-ev
sudo chmod 755 /var/lib/obd-ev

echo "[6/8] captive portal DNS + upload-on-connect hook"
# Wildcard DNS applies only while a `shared` connection is up, i.e. the setup
# access point.
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo cp "$REPO_DIR/systemd/obd-ev-portal-dns.conf" \
        /etc/NetworkManager/dnsmasq-shared.d/obd-ev-portal.conf
# Fire an upload the instant the Pi joins home WiFi rather than waiting for
# the timer; a participant may only be in range for a minute after parking.
sudo install -m 755 "$REPO_DIR/scripts/nm-dispatcher-upload" \
        /etc/NetworkManager/dispatcher.d/90-obd-ev-upload

echo "[7/8] install systemd units"
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
sudo systemctl enable obd-ev-provision.service
sudo systemctl enable obd-ev.service
sudo systemctl enable obd-ev-upload.timer

echo "[8/8] default env file"
# Default env file (overridable per-device).
if [ ! -f /etc/default/obd-ev ]; then
    # The setup access point needs a WPA2 password of its own. It is printed
    # on the kit's label; a random one per device is fine and preferable.
    ap_password="$(tr -dc 'a-z2-9' </dev/urandom | head -c 10)"
    sudo tee /etc/default/obd-ev >/dev/null <<ENVEOF
OBD_EV_LOG_DIR=$REPO_DIR/logs
OBD_EV_REMOTE=obd-ev:obd-ev-uploads
OBD_EV_RCLONE_CONF=$INSTALL_HOME/.config/rclone/rclone.conf
# Password for the "OBD-EV-Setup-<device id>" network the participant joins.
# PRINT THIS ON THE KIT LABEL.
OBD_EV_AP_PASSWORD=$ap_password
ENVEOF
    sudo chmod 600 /etc/default/obd-ev
    echo
    echo "  Setup-AP password for this device: $ap_password"
    echo "  (also in /etc/default/obd-ev; put it on the kit label)"
fi

echo
echo "System provisioning done."
if [ -z "${OBD_EV_FROM_SETUP_KIT:-}" ]; then
    echo "To build a complete kit (vehicle, cloud upload, checks), use:"
    echo "  ./scripts/setup_kit.sh"
fi
