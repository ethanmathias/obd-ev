#!/usr/bin/env bash
# Researcher-side imaging step. Run this ONCE per device (or on a master image)
# to configure rclone with credentials for the upload destination.
#
# The BLE OBD adapter is configured in config.yaml.
set -euo pipefail

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
