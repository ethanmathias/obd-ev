#!/usr/bin/env bash
# Put the Bluetooth controller into a state the BLE OBD adapter can be reached
# in. Run as root from obd-ev.service's ExecStartPre, so a kit repairs its own
# Bluetooth state on every boot rather than needing a hand.
#
# Two things go wrong otherwise, both of which look like broken hardware:
#
#   rfkill soft block   bleak reports "No powered Bluetooth adapters found"
#                       while the bluetooth service looks perfectly healthy.
#
#   dual-mode BlueZ     Device1.Connect() is transport-agnostic. For an address
#                       BlueZ holds BR/EDR information about it tries classic
#                       profiles and fails with
#                       "br-connection-profile-unavailable", even though the LE
#                       scan found the adapter fine. ControllerMode = le takes
#                       that choice away.
#
# Always exits 0: this must never be the reason the logger fails to start.
set -uo pipefail

BT_CONF=/etc/bluetooth/main.conf
changed=0

rfkill unblock bluetooth 2>/dev/null || true

if [ -f "$BT_CONF" ] \
   && ! grep -qE '^[[:space:]]*ControllerMode[[:space:]]*=[[:space:]]*le' "$BT_CONF"; then
    if grep -qE '^[[:space:]]*#?[[:space:]]*ControllerMode' "$BT_CONF"; then
        sed -i 's|^[[:space:]]*#\?[[:space:]]*ControllerMode.*|ControllerMode = le|' \
            "$BT_CONF" && changed=1
    elif grep -qE '^\[General\]' "$BT_CONF"; then
        sed -i '0,/^\[General\]/s//[General]\nControllerMode = le/' "$BT_CONF" && changed=1
    else
        printf '\n[General]\nControllerMode = le\n' >> "$BT_CONF" && changed=1
    fi
    [ "$changed" = 1 ] && echo "bt_prepare: set ControllerMode = le in $BT_CONF"
fi

if [ "$changed" = 1 ]; then
    # Only on the boot that actually changed it -- restarting bluetoothd on
    # every start would be gratuitous and would race the adapter coming up.
    systemctl restart bluetooth 2>/dev/null || true
    sleep 2
fi

# Make sure the controller is actually powered, whatever the stored state says.
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl power on >/dev/null 2>&1 || true
fi

exit 0
