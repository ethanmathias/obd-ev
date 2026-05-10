#!/usr/bin/env bash
# Upload pending CSV logs to the configured rclone remote.
# Idempotent: only uploads files in logs/ that aren't already in logs/uploaded/.
# Designed to be triggered by a systemd timer every few minutes; if there's
# no network, rclone fails fast and we just try again next tick.
set -euo pipefail

LOG_DIR="${OBD_EV_LOG_DIR:-$HOME/obd-ev/logs}"
REMOTE="${OBD_EV_REMOTE:-obd-ev:obd-ev-uploads}"   # rclone remote:path
RCLONE_CONF="${OBD_EV_RCLONE_CONF:-$HOME/.config/rclone/rclone.conf}"

mkdir -p "$LOG_DIR/uploaded"

# Quick connectivity test - skip silently if offline.
if ! ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; then
    exit 0
fi

shopt -s nullglob
csvs=("$LOG_DIR"/drive_*.csv)
[ ${#csvs[@]} -eq 0 ] && exit 0

# Don't upload the file currently being written. Heuristic: the newest one,
# IF logging service is active.
active_run=""
if systemctl is-active --quiet obd-ev; then
    active_run=$(ls -1t "$LOG_DIR"/drive_*.csv 2>/dev/null | head -1 || true)
fi

for csv in "${csvs[@]}"; do
    [ "$csv" = "$active_run" ] && continue

    name=$(basename "$csv")
    if rclone --config "$RCLONE_CONF" copyto "$csv" "$REMOTE/$name" \
            --retries 3 --low-level-retries 5; then
        # Move to local "uploaded" archive on success. Keep a copy locally
        # in case the remote ever needs to be re-verified.
        mv "$csv" "$LOG_DIR/uploaded/$name"
        echo "uploaded $name"
    else
        echo "upload failed for $name (will retry)" >&2
    fi
done
