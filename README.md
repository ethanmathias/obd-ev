# obd-ev

Raspberry Pi data logger for EVs, built for distribution to study
participants. The kit auto-connects to a BLE ELM327 OBD-II scanner, merges
vehicle telemetry with GPS and IMU data into a CSV per trip, and auto-uploads
completed logs to a cloud folder whenever it sees the participant's home WiFi.

Participants never hand over WiFi credentials: the device raises its own setup
network, and the password is converted to a WPA2 PMK **in the participant's
browser**, so the plaintext never reaches the device or the researchers.

## Design goals

- **Vehicle-specific where it counts** — point it at an
  [OBDb](https://github.com/OBDb) signalset for the make/model and it logs the
  manufacturer's own Mode 22 parameters: pack voltage and current, per-cell
  temperatures, true state of charge, per-wheel speed, steering angle. A 2024
  IONIQ 5 profile yields **381 signals** against the ~10 a generic scan gets.
- **Vehicle-agnostic fallback** — with no profile configured it logs a core set
  of Mode 01 PIDs, chosen for EV relevance, and probes which ones the ECU
  actually supports.
- **BLE OBD support** — connects to VEEPEAK-style BLE ELM327 adapters over
  GATT, with optional adapter MAC pinning in `config.yaml`.
- **Zero-touch for participants** — they join the device's setup network once
  from a phone, enter their home WiFi, and drive. No SD card handling, and no
  plaintext password anywhere in the system.
- **Resilient** — GPS and IMU record whether or not the OBD adapter ever
  answers; the vehicle link connects and reconnects on a background thread;
  trips rotate into separate files so uploads always have something to ship.

## Hardware

| Component | Part | Interface | Pi pins |
|-----------|------|-----------|---------|
| OBD scanner | BLE ELM327, e.g. VEEPEAK | Bluetooth LE | onboard radio |
| GPS | u-blox NEO-6M (GY-NEO6MV2) | UART | 3.3V, GND, GPIO14/15 |
| IMU | MPU-6050 (GY-521) | I2C | 3.3V, GND, GPIO2/3 |
| Host | Raspberry Pi 5 | — | — |

Wiring: see [docs/wiring.md](docs/wiring.md).

## Repo layout

```
obd-ev/
├── README.md
├── requirements.txt
├── config.yaml.example          # global defaults
├── obd-ev-wifi.conf.example     # lab WiFi preload (researcher only)
├── src/obd_ev/
│   ├── main.py                  # sample loop, trip rotation
│   ├── obd_reader.py            # background connect/reconnect supervisor
│   ├── ble_obd.py               # BLE ELM327 transport, Mode 01 PIDs
│   ├── obdb.py                  # OBDb signalset decoding (pure, tested)
│   ├── vehicle.py               # OBDb command scheduler over the BLE link
│   ├── gps_reader.py            # gpsd client, threaded
│   ├── imu_reader.py            # MPU-6050, threaded, per-row extremes
│   ├── logger.py                # CSV writer, one file per trip
│   ├── config.py                # YAML loader + env overrides
│   └── provision/               # participant WiFi onboarding
│       ├── server.py            #   AP + captive portal + nmcli
│       ├── portal.html          #   the page the participant sees
│       └── wpa.js               #   in-browser PBKDF2 -> WPA2 PMK
├── scripts/
│   ├── setup_pi.sh              # one-shot Pi provisioning
│   ├── image_setup.sh           # researcher: configure rclone
│   ├── fetch_signalset.py       # vendor a vehicle profile from OBDb
│   ├── authorize_kit.sh         # per-kit cloud authorization
│   ├── validate_obdb.py         # replay OBDb's own test vectors
│   ├── firstboot_wifi.sh        # lab-network preload (researcher only)
│   └── upload.sh                # rclone upload, idempotent
├── systemd/
│   ├── obd-ev.service           # main logger
│   ├── obd-ev-provision.service # participant WiFi setup portal
│   ├── obd-ev-upload.service    # one-shot upload
│   └── obd-ev-upload.timer      # backstop, fires every minute
├── tests/                       # decoder + portal tests
├── vehicles/                    # vendored OBDb signalsets
└── docs/
    ├── wiring.md
    ├── pid_reference.md
    ├── deployment.md            # researcher imaging guide
    └── participant.md           # what to put in the box
```

## Two audiences, two docs

- **Researchers** building/imaging kits: [docs/deployment.md](docs/deployment.md)
- **Participants** receiving a kit: [docs/participant.md](docs/participant.md)

## How it works at a glance

1. `obd-ev-provision.service` — on first boot, raises the
   `OBD-EV-Setup-<id>` access point and serves a captive setup page. The
   participant's browser derives the WPA2 PMK and posts only that; the Pi
   saves it as the network credential and never sees the passphrase. Once a
   network is provisioned this service never runs again.
2. `obd-ev.service` — starts GPS and IMU immediately, then connects to the
   vehicle on a background thread. Writes one CSV per trip, tagged with the
   device id, rotating when a trip ends so files become uploadable.
3. `obd-ev-upload` — fires on the NetworkManager dispatcher hook the instant
   the Pi joins a network, with a one-minute timer as a backstop. Uploaded
   files move to `logs/uploaded/`.

## Vehicle profiles

```bash
scripts/fetch_signalset.py --list ioniq
scripts/fetch_signalset.py Hyundai-IONIQ-5 --year 2024 --summary
```

```yaml
vehicle:
  signalset: vehicles/Hyundai-IONIQ-5.json
  make_model: Hyundai-IONIQ-5
  year: 2024
```

The decoder is checked against OBDb's own published test vectors —
**191,994 signal values across 8 EV models, all exact**. Re-run the sweep with:

```bash
scripts/validate_obdb.py --all-evs
python -m unittest discover -s tests     # fast, offline subset
```

## Cloud storage

Any rclone backend works (Box, Google Drive, Dropbox, S3…). Configured once
during imaging. The remote name in `/etc/default/obd-ev` must match what's in
`rclone.conf` (default: `obd-ev`).

For a fleet, each kit needs its own authorization — Box and Drive rotate OAuth
refresh tokens, so a token cloned across many cards breaks all but the first
kit to upload. Run `scripts/authorize_kit.sh` per card; it verifies the upload
and fingerprints the token so you can confirm no two kits match. See
[docs/cloud_setup.md](docs/cloud_setup.md).

## The data files

Each trip produces one CSV, and every run also writes `signals_<device>.csv` —
a data dictionary describing every column in it. Both are uploaded.

Column names are derived from the vehicle profile's own signal names and units,
so the CSV is readable without a decoder ring:

```
timestamp,t_mono,device_id,obd_connected,
front_left_wheel_speed_high_resolution_kph,steering_wheel_angle_deg,
lateral_acceleration_mps2,state_of_charge_pct,...,lat,lon,accel_x,...
```

`signals.csv` maps each one back to its origin, so a reviewer can check any
column against the upstream signalset:

| column | name | unit | group | source_id | command | period_s |
|---|---|---|---|---|---|---|
| `lateral_acceleration_mps2` | Lateral acceleration | metersPerSecondSquared | Orientation | `IONIQ5_LATERAL_ACCELERATION` | `22F010` | 0.25 |
| `state_of_charge_pct` | State of charge | percent | Battery | `IONIQ5_HVBAT_SOC_DISP` | `220101` | 1.0 |

`group` is the top-level category — `Battery`, `Movement`, `Orientation`,
`Tires`, `GPS`, `IMU`, `Meta` — and is the practical way to narrow a wide file:

```python
import pandas as pd
sig  = pd.read_csv("signals_P003.csv")
trip = pd.read_csv("drive_P003_20260901_143022.csv")

core = sig.loc[sig.group.isin(["Meta", "Movement", "Orientation", "GPS"]), "column"]
trip[core]                       # the 30-odd columns most analyses want
```

A full IONIQ 5 profile is 404 columns, of which 192 are individual battery cell
voltages (`Battery.Modules.NNN` in `category`). They cost almost nothing to
collect — all 192 arrive in 6 of the 33 requests — so they are captured, and
filtered out at analysis time rather than at collection time. To stop
collecting them entirely, use `vehicle.exclude_paths`.

## Notes on data quality

- **Acceleration.** GPS speed-delta gives cleaner forward/braking acceleration
  than the IMU (no gravity / mounting-angle problem). The IMU is logged raw
  and is most useful for lateral G and bumps.
- **OBD coverage.** With a vehicle profile, whatever that model exposes; see
  the `--summary` output. Without one, the configured Mode 01 PIDs — see
  [docs/pid_reference.md](docs/pid_reference.md). Note that RPM, coolant temp
  and engine load are meaningless on most EVs.
- **Row timing.** Each row carries `timestamp` (UTC), `t_mono` (monotonic, so
  intervals survive a clock jump when GPS finally sets the time) and
  `gps_age_s` / `imu_age_s`, so a repeated sensor value is distinguishable
  from a fresh one.
- **GPS cold start.** First fix can take 30s–2min. Mount with sky view.

## License

MIT — see [LICENSE](LICENSE).
