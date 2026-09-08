# Deployment guide (researcher)

## Build a kit

One script per SD card. There is no master image — cloning one would copy a
single cloud credential onto every kit, and Box invalidates a token when
another device refreshes it, so all but the first kit silently stop uploading.

1. Flash **Raspberry Pi OS Lite (64-bit)** with `rpi-imager`. Set a username,
   enable SSH, configure your own WiFi.
2. ```bash
   ssh <user>@raspberrypi.local
   git clone https://github.com/ethanmathias/obd-ev && cd obd-ev
   ./scripts/setup_kit.sh
   ```

10–15 minutes, mostly unattended package installation. Safe to re-run — every
step is idempotent, so a failure means fix-and-rerun, not start over.

| Step | |
|---|---|
| 1 Kit details | kit id + setup-WiFi password → `/etc/default/obd-ev` |
| 2 Vehicle | pick from a list, `s` searches all 205 known cars |
| 3 System | apt, I2C/UART, virtualenv, gpsd, systemd units |
| 4 Cloud | `rclone config`, then a real test upload |
| 5 Verify | `preflight.py`; non-zero exit if not shippable |
| 6 Label | prints the setup network name and password |

Label the kit with the setup network name and password. You never handle
participant WiFi credentials — they enter them on the device.

## Vehicle selection

```
  1) Chevrolet-Bolt-EUV               107 signals   107 commands  2022-2023
  2) Hyundai-IONIQ-5                  389 signals    34 commands  2021-2027
  0) (no profile)                  generic Mode 01, works on any OBD-II vehicle
  s) search all 205 known vehicles
```

Pick from the list rather than typing a name. A wrong name fails **silently**:
the kit falls back to generic Mode 01 and collects a fraction of the data with
nothing visibly broken. Choose `0` deliberately when the car isn't supported.

Change it later without rebuilding:

```bash
./scripts/select_vehicle.py && sudo systemctl restart obd-ev
```

## Cloud upload

Step 4 runs `rclone config` on that card, so each kit gets its own credential
automatically. Name the remote exactly **`obd-ev`** and pick `box`. The Pi has
no browser — answer **n** to "Use auto config?" and run the command it prints
on your laptop.

Two Box caveats: refresh tokens expire after ~60 days unused (fine in normal
operation, but a kit unplugged for two months needs re-authorizing), and
re-imaging means re-authorizing. If either becomes painful, a **Box JWT app**
has no user token and no expiry, but needs UVA Box admin approval.

Moving off Box is one line in `/etc/default/obd-ev`; rclone abstracts the
target. A Google **service account** needs a Shared Drive, not a My Drive
folder — service accounts have no storage quota of their own. An **API key**
(`AIzaSy...`) cannot do this at all; it carries no identity.

If you clone a finished card, run `./scripts/authorize_kit.sh` on the copy to
give it its own credential.

## The setup portal is held off while you build

`obd-ev-provision.service` puts `wlan0` into AP mode, which would disconnect
your SSH session. `setup_kit.sh` creates `/var/lib/obd-ev/setup-in-progress`
first, and the unit refuses to start while it exists — even across a reboot.
The lock is released only on clean completion; a failed run keeps it, so an
unfinished kit can't lock you out.

```bash
sudo touch /var/lib/obd-ev/setup-in-progress   # hold the AP off
sudo rm /var/lib/obd-ev/setup-in-progress      # re-arm before shipping
```

If a kit has already seized `wlan0` and you still have a shell:

```bash
sudo systemctl stop obd-ev-provision
sudo nmcli connection delete obd-ev-setup
sudo touch /var/lib/obd-ev/setup-in-progress
```

## How participant onboarding works

On first boot the Pi raises `OBD-EV-Setup-<id>` on 10.42.0.1 with wildcard DNS,
so phones auto-open the setup page. The participant picks their network and
types the password; **the browser derives the WPA2 PMK**
(`PBKDF2-HMAC-SHA1(passphrase, ssid, 4096)`) and posts only that. The Pi saves
it as the network credential, drops the AP, and joins to verify. On success it
writes `/var/lib/obd-ev/provisioned.json` and never runs again; on failure the
AP returns so the password can be corrected.

The stored PMK cannot be reversed into the passphrase — that is the point, since
participants reuse passwords — but it is still a credential for that network, so
treat returned SD cards as sensitive. **WPA3-SAE-only networks can't be joined
from a PMK**; the page detects this, warns on screen, and only then falls back
to sending the passphrase. `provisioned.json` records which method was used.

Re-provision a kit:

```bash
sudo rm /var/lib/obd-ev/provisioned.json
sudo nmcli connection delete obd-ev-home
sudo reboot
```

## Files and uploads

```
obd-ev-uploads/P003/20260906_142201_a3f9c1d2/
    drive_P003_20260906_142201.csv
    drive_P003_20260906_143701.csv     # part, after a 15-minute rotation
    signals_P003.csv                   # dictionary for these files
```

Trip folders are `<timestamp>_<boot id>`. The Pi has no RTC, so two power
cycles can report the same wall time; the boot id keeps them distinct. Sort by
the `timestamp` column, not by folder name.

`signals.csv` is written per trip, not per device — the schema changes if a
profile is updated or a kit reassigned, and a shared dictionary would start
lying about older trips.

A **new trip** starts on logger start and when the vehicle returns after
`trip_gap_seconds`. A **new part** starts every `rotate_minutes` and when a trip
goes quiet. On most cars power dies with the ignition, so one trip is one power
cycle. The logger records its open file in `logs/.current`; `upload.sh` skips
it, but only while the service is running — after an unclean shutdown that file
is complete and uploads normally.

Uploads fire on the NetworkManager dispatcher hook the moment the Pi joins a
network, with a one-minute timer as backstop. Shipped trips move to
`logs/uploaded/<trip>/`, pruned to the most recent 64.

## Field checks

```bash
./scripts/preflight.py                       # everything, exits non-zero on failure
./scripts/sensors.py                         # live GPS + IMU readings
journalctl -u obd-ev -f                      # is it logging?
cat /var/lib/obd-ev/provisioned.json         # did the participant set WiFi?
journalctl -u obd-ev | grep -i 'retiring\|falling back'   # unanswered commands
sudo systemctl start obd-ev-upload           # force an upload
```

## When a kit comes back

```bash
cd ~/obd-ev/logs/uploaded && rm -rf */       # already in the cloud
sudo nmcli connection delete obd-ev-home     # forget their network
sudo rm -f /var/lib/obd-ev/provisioned.json /var/lib/obd-ev/upload-authorized.json
sudo journalctl --vacuum-time=1d
```

Then re-flash and rebuild for the next participant.

## Checking the sensors

```bash
./scripts/sensors.py            # both, 1 Hz          --gps / --imu / --once
```

```
22:44:00  GPS  fix=3D  sats=9   38.033554, -78.507980  alt 182.4m  speed 0.1 m/s  age 0.3s
22:44:00  IMU  accel   0.12  -0.05   9.79 m/s2   gyro  0.01  0.00 -0.02 deg/s   |a|max  9.81  n=98
```

This drives the same reader classes the logger uses, so a clean run means the
logging path works, not just that something is on the bus. `n=` is the number
of IMU samples since the previous line — if it stays 0 the sensor isn't
responding.

Lower-level alternatives if you need them: `cgps -s` or `gpspipe -w` for GPS,
`i2cdetect -y 1` to confirm the IMU answers at `0x68`.
