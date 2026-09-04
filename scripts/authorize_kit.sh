#!/usr/bin/env bash
# Give THIS kit its own cloud authorization. Run once per SD card, after
# flashing the master image and before shipping.
#
# Why this exists: the master image carries one Box/Drive login. Cloning it
# gives every kit the same OAuth refresh token, and these providers issue a
# replacement token on each refresh and invalidate the old one -- so the first
# kit to upload silently breaks all the others. Re-authorizing here gives each
# kit an independent token, which is all it takes to avoid that.
#
# The token itself is never printed. A short fingerprint is recorded so you can
# confirm at a glance that no two kits ended up sharing one.
set -euo pipefail

REMOTE_SPEC="${OBD_EV_REMOTE:-obd-ev:obd-ev-uploads}"
REMOTE_NAME="${REMOTE_SPEC%%:*}"
RCLONE_CONF="${OBD_EV_RCLONE_CONF:-$HOME/.config/rclone/rclone.conf}"
STATE_DIR="/var/lib/obd-ev"
MARKER="$STATE_DIR/upload-authorized.json"

# Pick up per-kit settings (device id, remote) the same way the services do.
[ -f /etc/default/obd-ev ] && . /etc/default/obd-ev
DEVICE_ID="${OBD_EV_DEVICE_ID:-$(hostname)}"

rc() { rclone --config "$RCLONE_CONF" "$@"; }

# Fingerprint = first 12 hex of sha256 over the remote's stored token. Enough
# to compare kits; useless to anyone who obtains it.
fingerprint() {
    rc config dump 2>/dev/null | python3 -c '
import hashlib, json, sys
try:
    remotes = json.load(sys.stdin)
except Exception:
    print("none"); sys.exit()
tok = (remotes.get(sys.argv[1]) or {}).get("token", "")
print(hashlib.sha256(tok.encode()).hexdigest()[:12] if tok else "none")
' "$REMOTE_NAME"
}

if ! rc config show "$REMOTE_NAME" >/dev/null 2>&1; then
    echo "No rclone remote named '$REMOTE_NAME' in $RCLONE_CONF." >&2
    echo "Set it up on the master image first: scripts/image_setup.sh" >&2
    exit 1
fi

before="$(fingerprint)"
echo "=== Per-kit cloud authorization ==="
echo "  device      : $DEVICE_ID"
echo "  remote      : $REMOTE_SPEC"
echo "  token now   : $before   (inherited from the master image)"
echo
echo "This re-runs the provider's login so this kit gets its own token."
echo "The Pi has no browser, so rclone will print a command to run on your"
echo "laptop; paste the result back here when it asks."
echo
read -r -p "Press Enter to start, or Ctrl-C to abort. "

rc config reconnect "${REMOTE_NAME}:"

after="$(fingerprint)"
echo
if [ "$after" = "none" ]; then
    echo "No token stored after reconnect -- authorization did not complete." >&2
    exit 1
fi
if [ "$after" = "$before" ]; then
    echo "WARNING: the token is unchanged ($after)." >&2
    echo "This kit is still sharing the master image's credential, which is the" >&2
    echo "exact situation this script exists to prevent. Re-run and complete the" >&2
    echo "browser step." >&2
    exit 1
fi

echo "Token is new for this kit: $before -> $after"
echo
echo "Verifying an actual upload..."
probe="_authcheck_${DEVICE_ID}_$$"
if echo "obd-ev authorization check" | rc rcat "$REMOTE_SPEC/$probe"; then
    rc delete "$REMOTE_SPEC/$probe" >/dev/null 2>&1 || true
    echo "Upload verified."
else
    echo "Upload FAILED even though authorization succeeded." >&2
    echo "Check that $REMOTE_SPEC exists and is writable." >&2
    exit 1
fi

record="$(printf '{\n "device_id": "%s",\n "remote": "%s",\n "token_fingerprint": "%s",\n "authorized_at": "%s"\n}\n' \
    "$DEVICE_ID" "$REMOTE_SPEC" "$after" "$(date -Is)")"
if ! printf '%s' "$record" | sudo tee "$MARKER" >/dev/null 2>&1; then
    echo "(could not write $MARKER -- not fatal)" >&2
else
    sudo chmod 644 "$MARKER" 2>/dev/null || true
fi

echo
echo "Done. Record this kit in your build log:"
echo "  $DEVICE_ID  ->  $after"
echo
echo "Every kit must show a DIFFERENT fingerprint. Two matching kits means one"
echo "of them was cloned after authorization and will stop uploading."
