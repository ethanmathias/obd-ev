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

# Wait briefly for NetworkManager. If the Pi is away from home WiFi, this
# exits quietly and the systemd timer will try again on the next tick.
if command -v nm-online >/dev/null 2>&1 && ! nm-online -q -t 10; then
    exit 0
fi

shopt -s nullglob

# The data dictionary describes every column in the trip files, so it has to
# reach the cloud folder too. It is small, fixed for the run, and rewritten on
# each boot, so just overwrite it every time rather than tracking it.
for dict_file in "$LOG_DIR"/signals*.csv; do
    rclone --config "$RCLONE_CONF" copyto "$dict_file" \
        "$REMOTE/$(basename "$dict_file")" --retries 2 >/dev/null 2>&1 || true
done

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

uploaded=("$LOG_DIR"/uploaded/drive_*.csv)
if [ ${#uploaded[@]} -gt 256 ]; then
    ls -1t "$LOG_DIR"/uploaded/drive_*.csv | tail -n +257 | xargs -r rm -f
fi
