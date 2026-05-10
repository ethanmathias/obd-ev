#!/usr/bin/env bash
# First-boot WiFi provisioning for participants.
#
# At image time, the participant edits /boot/firmware/obd-ev-wifi.conf on the
# SD card with their home SSID and password. On first boot this script reads
# that file and creates a NetworkManager connection profile. After that, the
# Pi auto-connects whenever it's in range.
#
# Multiple networks may be supplied (one block per network).
#
# File format:
#   ssid=MyHomeWiFi
#   psk=mypassword
#   ---
#   ssid=Backup
#   psk=otherpassword
set -euo pipefail

CONF="/boot/firmware/obd-ev-wifi.conf"

if [ ! -f "$CONF" ]; then
    echo "no wifi config at $CONF, skipping"
    exit 0
fi

# Split file into blocks separated by lines of dashes.
awk -v RS='---\n' '{print > "/tmp/wifi_block_" NR ".tmp"}' "$CONF"

for block in /tmp/wifi_block_*.tmp; do
    [ -s "$block" ] || continue
    ssid=$(grep -E '^ssid=' "$block" | head -1 | cut -d= -f2- | tr -d '\r')
    psk=$(grep -E '^psk='  "$block" | head -1 | cut -d= -f2- | tr -d '\r')
    [ -z "$ssid" ] && continue

    echo "adding network: $ssid"
    if [ -z "$psk" ]; then
        nmcli -t connection add type wifi ifname wlan0 \
            con-name "$ssid" ssid "$ssid" || true
    else
        nmcli -t connection add type wifi ifname wlan0 \
            con-name "$ssid" ssid "$ssid" \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" || true
    fi
    nmcli connection modify "$ssid" connection.autoconnect yes
done

rm -f /tmp/wifi_block_*.tmp

# Mark this run done so we don't re-process on every boot.
mv "$CONF" "${CONF}.applied"
echo "wifi provisioning done"
