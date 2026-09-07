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
   ./scripts/select_vehicle.py --search bolt      # search the catalogue
   ./scripts/fetch_signalset.py Chevrolet-Bolt-EUV --year 2023 --summary
   ./scripts/fetch_signalset.py Hyundai-IONIQ-5   --year 2024 --summary
   ```
   `vehicles/index.json` is the catalogue of every OBDb vehicle that actually
   has data — 205 of 733 repos; the rest are empty placeholders. Regenerate it
   with `./scripts/build_index.py` when you want to pick up new models.
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
2. Set the kit identifier and setup-AP password in `/etc/default/obd-ev`:
   ```sh
   # Appears in every CSV row, in the upload path, and in the setup network
   # name (OBD-EV-Setup-P003).
   OBD_EV_DEVICE_ID=P003

   # Password for this kit's setup network. Goes on the label.
   OBD_EV_AP_PASSWORD=<printed on the kit label>
   ```

3. **Pick the vehicle from a list** rather than typing it:
   ```bash
   ./scripts/select_vehicle.py
   ```
   ```
   Vehicle profiles on this image:

     1) Chevrolet-Bolt-EUV          107 signals  107 commands  2022-2023
     2) Hyundai-IONIQ-5             381 signals   33 commands  2021-2027
     0) (no profile)              generic Mode 01, works on any OBD-II vehicle

   Select [0-2]: 1
   Model year [2022, 2023]: 2023
   ```
   It shows what will be collected, validates the model year against the
   vehicle's known generations, and writes `OBD_EV_VEHICLE` /
   `OBD_EV_VEHICLE_YEAR` without disturbing the rest of the file.

   Use the picker rather than editing by hand. A mistyped vehicle name is the
   worst failure mode in this whole setup because it is **silent**: the kit
   falls back to generic Mode 01 and collects a fraction of the data with
   nothing visibly wrong. Choose `0` deliberately if the participant's car
   isn't supported.

   `--all` or `--search <term>` widens the list to the whole catalogue rather
   than just what is on the image; picking one that isn't installed downloads
   it first, so that step needs network.

   Scriptable equivalents: `--set Chevrolet-Bolt-EUV --year 2023`, `--none`,
   `--list`.
4. **Give this kit its own cloud authorization:**
   ```bash
   ./scripts/authorize_kit.sh
   ```
   Every kit needs its own — the master image's token is shared, and Box and
   Drive invalidate a token when another device refreshes it, which silently
   stops uploads on every other kit. The script verifies a real upload and
   records a token fingerprint; note it in your build log and confirm no two
   kits match. See [docs/cloud_setup.md](cloud_setup.md).
5. **Run the preflight check.** It exits non-zero if anything would stop this
   kit collecting or uploading:
   ```bash
   ./scripts/preflight.py
   ```
   It verifies the vehicle profile actually resolves, the IMU answers on I2C,
   gpsd is producing fixes, the upload credential is this kit's own, the
   services are enabled, and that the setup portal will still run for the
   participant. Every check is something with no visible symptom in the field.

6. **Label the kit** with the setup network name and setup password.
7. Ship it. Participant WiFi credentials are never handled by you — the
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

Every kit uploads into the same folder, so the layout is keyed by device first
and trip second:

```
obd-ev-uploads/
  P003/
    20260906_142201_a3f9c1d2/          <- one trip
      drive_P003_20260906_142201.csv
      drive_P003_20260906_143701.csv   <- part, after a 15-minute rotation
      signals_P003.csv                 <- data dictionary for these files
    20260906_181044_7b2e0a55/
      ...
  P004/
    ...
```

**Trip folder names are `<timestamp>_<boot id>`.** The timestamp is from the Pi
clock, which has no RTC and is wrong until GPS or NTP corrects it — so two
power cycles can genuinely report the same wall time. The kernel boot id makes
the folder unique regardless, and a same-second collision within one boot gets a
numeric suffix. Sort by the `timestamp` column inside the files, not by folder
name, when the ordering has to be exact.

`signals_<device>.csv` is written into **each** trip folder rather than once per
device. The schema changes if a vehicle profile is updated or a kit reassigned,
and a dictionary sitting next to the data it describes stays correct where a
single shared one would silently start lying about older trips.

Locally the same layout appears under `logs/`, and uploaded trips move to
`logs/uploaded/<trip>/` — kept as a re-verification copy, pruned to the most
recent `OBD_EV_KEEP_TRIPS` (default 64) once the card has shipped them.

## Trip files and uploads

The logger records the file it currently has open in `logs/.current`, and
`upload.sh` skips exactly that file — but only while `obd-ev` is actually
running. After an unclean shutdown the marker is stale and the file it names is
complete, so it uploads normally on the next tick.

A **new trip folder** starts when the logger starts, and when the vehicle
answers again after being unreachable for `logger.trip_gap_seconds`.

A **new part** inside the current trip starts every `logger.rotate_minutes`,
and when a trip goes quiet. Parts exist because power is cut without warning:
rotating bounds how much one unclean shutdown can cost, and closing a file is
what makes it eligible for upload.

On most cars the Pi loses power the moment the ignition goes off, so in practice
**one trip is one power cycle** and the `trip_gap_seconds` path rarely fires.
A car parked for a week with the port still live produces one idle part, not
hundreds of files.

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
