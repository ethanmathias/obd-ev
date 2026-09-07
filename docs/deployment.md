# Deployment guide (researcher)

How to build a master SD card image, then customize it per participant kit.
The study workflow is:

1. The Pi logs one CSV per trip segment.
2. CSVs stay on the Pi while the participant is away from home.
3. When the Pi joins the participant's home WiFi, pending CSVs upload to the
   rclone cloud remote and move locally to `logs/uploaded/`.

## Build a kit

One script per SD card, start to finish. There is no master image.

1. **Flash Raspberry Pi OS Lite (64-bit)** with `rpi-imager`. Set a username,
   enable SSH, and configure your own WiFi so you can reach the Pi.

2. **Clone and run:**
   ```bash
   ssh <user>@raspberrypi.local
   git clone https://github.com/ethanmathias/obd-ev && cd obd-ev
   ./scripts/setup_kit.sh
   ```

That is the whole process. Expect 10-15 minutes, most of it unattended package
installation. The script asks for everything up front, then leaves you alone
until the cloud login, which needs a browser on your laptop.

It is safe to re-run: every step is idempotent, so if something fails you fix
it and run the script again rather than starting the card over.

### Why not a master image

Cloning an image copies one cloud credential onto every kit. Box and Google
Drive both rotate OAuth refresh tokens — when one device refreshes, the copies
every other kit holds stop working. The failure is silent and shows up weeks
later as missing data from unattended devices.

Building each card fresh gives it its own credential, so the problem cannot
occur. It costs about ten minutes of mostly unattended time per kit, which is
a good trade below a few dozen kits.

If you *do* clone a card, run `scripts/authorize_kit.sh` on the copy to give it
its own credential.

### What the script does

| Step | |
|---|---|
| 1. Kit details | Asks for the kit id and setup-WiFi password, writes `/etc/default/obd-ev` |
| 2. Vehicle | Pick from a list; downloads the profile if it isn't local yet |
| 3. System | apt packages, I2C and UART, virtualenv, gpsd, systemd units |
| 4. Cloud | `rclone config`, then a real test upload |
| 5. Verify | Runs `preflight.py`; exits non-zero if the kit isn't shippable |
| 6. Label | Prints the setup network name and password for the label |

It also clears `/var/lib/obd-ev/provisioned.json`, so the participant gets the
WiFi setup portal on first boot even though you connected the Pi to your own
network while building it.

### The setup portal is held off while you build

`obd-ev-provision.service` puts `wlan0` into access-point mode. If it started
while you were still building the card it would disconnect your own SSH
session, so `setup_kit.sh` creates `/var/lib/obd-ev/setup-in-progress` before
it does anything, and the unit refuses to start while that file exists — even
across a reboot. The lock is released only when the script completes cleanly,
which is also when the portal is armed for the participant's first boot.

If a run fails part-way, the lock stays in place. That is deliberate: an
unfinished kit must not seize the radio and lock you out of the card you are
still working on.

Need more SSH time on a finished kit:

```bash
sudo touch /var/lib/obd-ev/setup-in-progress   # hold the AP off
sudo rm /var/lib/obd-ev/setup-in-progress      # re-arm before shipping
```

If a kit has already seized `wlan0` and you still have a shell:

```bash
sudo systemctl stop obd-ev-provision
sudo nmcli connection down obd-ev-setup
sudo nmcli connection delete obd-ev-setup
sudo touch /var/lib/obd-ev/setup-in-progress
```

### The vehicle step

```
Vehicle profiles on this image:

  1) Chevrolet-Bolt-EUV               107 signals   107 commands  2022-2023
  2) Hyundai-IONIQ-5                  389 signals    34 commands  2021-2027
  0) (no profile)                  generic Mode 01, works on any OBD-II vehicle

Select [0-2]: 1
Model year [2022, 2023]: 2023
```

Selection is from a list rather than typed, because a mistyped vehicle name is
the worst failure in this setup: it is **silent**, and the kit quietly falls
back to generic Mode 01 and collects a fraction of the data.

Searching spans the full OBDb catalogue (`vehicles/index.json`, 205 vehicles
that actually have data out of 733 repos), and picking one that isn't on the
card downloads it. Choose `0` deliberately when the participant's car isn't
supported.

Re-run just this step later without rebuilding the card:

```bash
./scripts/select_vehicle.py            # or --all / --search bolt
sudo systemctl restart obd-ev
```

### Adding a vehicle to the catalogue

`vehicles/index.json` is a snapshot. If OBDb has added a model since:

```bash
./scripts/build_index.py
```

### Ship it

Label the kit with the setup network name and password the script printed.
Participant WiFi credentials are never handled by you — the participant enters
them on the device itself.

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

## Cloud credentials

Because each card is built from scratch, each runs its own `rclone config` and
gets its own credential. Nothing further is needed.

The one exception is cloning: if you copy a finished card rather than building
a new one, both hold the same token and one will stop uploading. Run
`scripts/authorize_kit.sh` on the copy.

Setup details and alternatives to Box: **[docs/cloud_setup.md](cloud_setup.md)**.

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
