#!/usr/bin/env bash
# Researcher-side imaging step. Run this ONCE per device (or on a master image)
# to:
#   1. Pair the OBD adapter that ships in the kit
#   2. Configure rclone with credentials for the upload destination
#
# After this, drop a /boot/firmware/obd-ev-wifi.conf onto the SD card with
# the participant's home WiFi and ship.
set -euo pipefail

echo "=== OBD adapter pairing ==="
echo "Power on the ELM327 (plug into a car or 12V source) and put it in"
echo "pairing mode. Press Enter to start scanning."
read -r

sudo python3 "$(dirname "$0")/obd_pair.py" --discover --scan-seconds 30

echo
echo "=== rclone configuration ==="
echo "This launches rclone's interactive setup. Choose:"
echo "  - name:    obd-ev      (must match OBD_EV_REMOTE in /etc/default/obd-ev)"
echo "  - storage: 'box' or 'drive'"
echo "  - follow the OAuth flow on a browser"
echo
echo "Press Enter to launch rclone config."
read -r

rclone config

echo
echo "Test:"
echo "  rclone lsd obd-ev:"
echo "If that lists folders, you're done."
