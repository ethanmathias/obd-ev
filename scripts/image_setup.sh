#!/usr/bin/env bash
# Configure rclone for the upload destination.
#
# `scripts/setup_kit.sh` does this as part of building a kit, so you only need
# this to repair or change the destination on a card that already exists.
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
