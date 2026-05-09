#!/usr/bin/env bash
# Bind an ELM327 Bluetooth OBD scanner to /dev/rfcomm0.
# Usage: sudo ./rfcomm_bind.sh AA:BB:CC:DD:EE:FF [channel]
set -euo pipefail

MAC="${1:-}"
CHANNEL="${2:-1}"

if [[ -z "$MAC" ]]; then
    echo "Usage: $0 <bt_mac> [channel]"
    echo "Find your adapter MAC with: bluetoothctl scan on"
    exit 1
fi

# Pair + trust so the adapter reconnects without a prompt.
bluetoothctl <<EOF
power on
agent on
default-agent
pair $MAC
trust $MAC
EOF

# Persistent rfcomm binding via systemd unit.
SERVICE=/etc/systemd/system/rfcomm-bind.service
sudo tee "$SERVICE" >/dev/null <<UNIT
[Unit]
Description=Bind ELM327 to /dev/rfcomm0
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/bin/rfcomm bind 0 $MAC $CHANNEL
ExecStop=/usr/bin/rfcomm release 0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now rfcomm-bind.service
echo "Bound $MAC to /dev/rfcomm0"
