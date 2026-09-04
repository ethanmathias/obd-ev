# Deployment guide (researcher)

How to build a master SD card image, then customize it per participant kit.
The study workflow is:

1. The Pi logs one CSV per trip segment.
2. CSVs stay on the Pi while the participant is away from home.
3. When the Pi joins the participant's home WiFi, pending CSVs upload to the
   rclone cloud remote and move locally to `logs/uploaded/`.

## One-time master image

1. **Flash Raspberry Pi OS Lite (64-bit).** Use `rpi-imager`. Set any
   username, enable SSH, and configure your *own* WiFi (not the
   participant's) so you can finish setup over the network. The setup script
   installs services for whichever user runs it.

2. **Clone and provision.**
   ```bash
   ssh <username>@raspberrypi.local
   git clone https://github.com/ethanmathias/obd-ev
   cd obd-ev
   ./scripts/setup_pi.sh
   sudo reboot
   ```
   `setup_pi.sh` prints a randomly generated **setup-AP password** and stores
   it in `/etc/default/obd-ev`. Write it down — it goes on the kit label.

3. **Configure the BLE OBD adapter.**
   ```bash
   cp -n config.yaml.example config.yaml
   nano config.yaml
   ```
   ```yaml
   obd:
     ble_address: 8C:DE:52:DD:FD:37   # adapter MAC, or null to discover by name
     ble_name: VEEPEAK
   ```

4. **Add the vehicle profiles.** This is the step that decides how much data
   you actually collect. Generic Mode 01 yields about ten values; a
   vehicle-specific OBDb signalset yields hundreds, including the EV
   parameters that matter.

   Fetch **one profile per vehicle model in the study**, into the master image,
   so any kit can be assigned to any of those cars later without re-imaging:
   ```bash
   ./scripts/fetch_signalset.py --list bolt
   ./scripts/fetch_signalset.py Chevrolet-Bolt-EUV --year 2023 --summary
   ./scripts/fetch_signalset.py Hyundai-IONIQ-5   --year 2024 --summary
   ```
   Each writes `vehicles/<Make-Model>.json`. Read the `--summary` output before
   committing to a model: coverage varies enormously. A 2024 IONIQ 5 exposes
   381 signals including steering, yaw and acceleration; a Bolt EUV exposes 107,
   of which 96 are battery module voltages and only one is a non-battery signal.

   Leave `config.yaml`'s `vehicle:` block alone — which car a given kit is for
   is set per participant, below. Set it in `config.yaml` only if every kit in
   the study is the same model.

   If a model isn't in OBDb, or its repo exists but has no commands yet (Tesla
   and Rivian are currently empty stubs), skip it: that kit falls back to
   generic Mode 01 automatically.

5. **Configure cloud upload.**
   ```bash
   ./scripts/image_setup.sh
   ```
   - Name the remote **`obd-ev`** and pick `box` or `drive`.
   - Verify with `rclone lsd obd-ev:`.
   - **Read [docs/cloud_setup.md](cloud_setup.md) first if you are imaging more
     than one or two kits** — the interactive login stores a credential that
     breaks when cloned across a fleet.

6. **Test the full pipeline.**
   ```bash
   sudo systemctl start obd-ev
   journalctl -u obd-ev -f
   ```
   Confirm a CSV appears in `~/obd-ev/logs/` and that the column count matches
   the signalset summary. Then force an upload:
   ```bash
   sudo systemctl start obd-ev-upload
   ```

7. **Clear the provisioning marker before imaging**, so the setup portal runs
   on the participant's first boot:
   ```bash
   sudo rm -f /var/lib/obd-ev/provisioned.json
   sudo journalctl --vacuum-time=1d
   ```

8. **Shut down and clone the SD card** with `dd`, Pi Imager, or
   [PiShrink](https://github.com/Drewsif/PiShrink).

## Per-participant customization

1. Flash the master image to a fresh SD card.
2. Mount the rootfs and edit `/etc/default/obd-ev`. This is the only
   per-participant file:
   ```sh
   # Kit identifier. Appears in every CSV row, in the uploaded filename, and
   # in the setup network name (OBD-EV-Setup-P003).
   OBD_EV_DEVICE_ID=P003

   # Which car this kit is going into. The name is the OBDb repo name, and
   # must match a file already fetched into vehicles/ on the master image.
   OBD_EV_VEHICLE=Chevrolet-Bolt-EUV
   OBD_EV_VEHICLE_YEAR=2023

   # Password for this kit's setup network. Goes on the label.
   OBD_EV_AP_PASSWORD=<printed on the kit label>
   ```
   Omit `OBD_EV_VEHICLE` entirely if the participant's car is unknown or
   unsupported — the kit then logs the generic Mode 01 set, which works on any
   OBD-II compliant vehicle. `OBD_EV_VEHICLE_YEAR` selects year-filtered
   commands and is worth setting whenever you know it.
3. **Give this kit its own cloud authorization:**
   ```bash
   ./scripts/authorize_kit.sh
   ```
   Every kit needs its own — the master image's token is shared, and Box and
   Drive invalidate a token when another device refreshes it, which silently
   stops uploads on every other kit. The script verifies a real upload and
   records a token fingerprint; note it in your build log and confirm no two
   kits match. See [docs/cloud_setup.md](cloud_setup.md).
4. **Label the kit** with the setup network name and setup password.
5. Ship it. Participant WiFi credentials are never handled by you — the
   participant enters them on the device itself.

These variables override `config.yaml`, because `config.yaml` is baked into the
master image and this file is not. A name with no matching file in `vehicles/`
logs an error and falls back to generic Mode 01 rather than taking the kit
offline, so a typo costs vehicle signals but never a whole drive. Confirm which
path a kit took on first boot:

```bash
journalctl -u obd-ev | grep -E "vehicle profile|falling back"
```

> `obd-ev-wifi.conf` on the boot partition still exists, and
> `scripts/firstboot_wifi.sh` still applies it. That path writes a plaintext
> passphrase to a FAT partition, so use it **only for your own lab network
> during imaging**, never for participant credentials.

## How participant WiFi onboarding works

On first boot, `obd-ev-provision.service` sees no
`/var/lib/obd-ev/provisioned.json` and:

1. Scans for nearby networks (before the AP is raised — a single radio cannot
   be an access point and scan at the same time, so this cached list is what
   the participant is offered, plus a manual-entry option).
2. Raises a WPA2 access point `OBD-EV-Setup-<device id>` on `10.42.0.1`, with
   wildcard DNS so phones auto-open the setup page.
3. Serves the page. The participant picks their network and types the password.
4. **The browser derives the WPA2 PMK** — `PBKDF2-HMAC-SHA1(passphrase, ssid,
   4096, 256 bits)` — and posts only that 64-hex digest. The passphrase never
   leaves the phone.
5. The Pi saves a NetworkManager profile using the PMK in place of the
   passphrase (NetworkManager accepts a raw PMK anywhere it accepts one), drops
   the AP, and joins the network to verify it works.
6. On success it writes `/var/lib/obd-ev/provisioned.json` and the service
   never runs again. On failure the AP comes back so the password can be
   corrected.

### What this does and does not protect

- The stored PMK **cannot be reversed** into the participant's passphrase, so a
  password they reuse elsewhere stays protected. This is the main goal.
- The PMK **is still a credential for that network**. Anyone holding it can
  join. Treat returned SD cards as sensitive and wipe them.
- **WPA3-SAE-only networks cannot be joined from a PMK.** The page detects this
  from the scan, warns the participant on screen, and only then falls back to
  sending the passphrase. `provisioned.json` records which method was used, so
  you can audit it per kit.
- The passphrase is never logged: the portal's request logging is suppressed
  precisely because a fallback passphrase would otherwise land in the journal.

### Re-provisioning a kit

Participant changed their WiFi password, or the kit is being reissued:

```bash
sudo rm /var/lib/obd-ev/provisioned.json
sudo nmcli connection delete obd-ev-home
sudo reboot
```

## What the Pi does on power-up

1. Boots, NetworkManager starts.
2. `obd-ev-provision.service` runs the setup portal if no network is
   provisioned yet; otherwise it does nothing.
3. `obd-ev.service` starts logging immediately. GPS and IMU record whether or
   not the OBD adapter ever answers, and the OBD link connects and reconnects
   on a background thread.
4. Uploads fire on the NetworkManager dispatcher hook the moment the Pi joins a
   network, and on the timer every minute as a backstop.

## What lands in the cloud folder

```
drive_P003_20260901_143022.csv     one trip, all columns
drive_P003_20260901_145510.csv
signals_P003.csv                   data dictionary for this kit
```

`signals_P003.csv` documents every column in the trip files — readable name,
unit, top-level `group`, the OBDb signal id and command it came from, and the
polling period. It is rewritten each boot and re-uploaded each time, so it
always matches the vehicle profile the kit is actually running.

Column names are normalized from the signalset (`lateral_acceleration_mps2`,
`state_of_charge_pct`). Where two signals would produce the same name, the
second keeps its vendor id as the column instead, so no column is ever
silently overwritten — check `source_id` in the dictionary if a name looks odd.

## Trip files and uploads

`upload.sh` never uploads the file the logger is currently writing, so a file
only ships once it has been rotated. Rotation happens when:

- the vehicle has been unreachable for `logger.trip_gap_seconds` (trip over),
- the vehicle answers again after a gap (a new trip starts), or
- an active trip passes `logger.rotate_minutes`.

A car parked for a week produces one idle file, not hundreds.

## Cloud credentials for a fleet

Box is fine — keep it. The one rule is that **each kit needs its own
authorization**, because Box and Drive rotate OAuth refresh tokens: when one
device refreshes, every other device holding a copy of that token stops working,
silently.

So: authorize once on the master image, then run `scripts/authorize_kit.sh` on
each card after flashing. About a minute per kit.

Full detail, including how to confirm no two kits share a credential:
**[docs/cloud_setup.md](cloud_setup.md)**.

## Quick checks in the field

```bash
# Was a home network provisioned, and how?
cat /var/lib/obd-ev/provisioned.json
nmcli connection show

# Is logging running, and how wide are the rows?
journalctl -u obd-ev -f
head -1 ~/obd-ev/logs/*.csv | tr ',' '\n' | wc -l

# Which vehicle commands went unanswered?
journalctl -u obd-ev | grep -i 'retiring\|not report'

# Force an upload
sudo systemctl start obd-ev-upload
journalctl -u obd-ev-upload --no-pager -n 50

# Which credential is this kit using, and when was it authorized?
cat /var/lib/obd-ev/upload-authorized.json
```

## When a kit comes back

```bash
ssh <username>@<device>
cd ~/obd-ev/logs/uploaded && rm -f *.csv     # already in the cloud
sudo nmcli connection delete obd-ev-home     # forget their network
sudo rm -f /var/lib/obd-ev/provisioned.json
sudo journalctl --vacuum-time=1d
```

Then re-flash the SD card and re-personalize for the next participant.
