# obd-ev

Raspberry Pi data logger for vehicles, built for distribution to study
participants. The kit auto-connects to a BLE ELM327 OBD-II scanner,
merges live OBD telemetry with GPS and IMU data into a CSV per drive, and
auto-uploads completed logs to a cloud folder whenever it sees the
participant's home WiFi.

## Design goals

- **Vehicle-agnostic** — logs a core set of widely supported Mode 01 PIDs.
  Works on most 1996+
  OBD-II compliant cars.
- **BLE OBD support** — connects to VEEPEAK-style BLE ELM327 adapters over
  GATT, with optional adapter MAC pinning in `config.yaml`.
- **Zero-touch for participants** — they edit one file on the SD card to set
  their home WiFi, plug in, and drive.
- **Resilient** — retries OBD connection until the car starts, queues uploads
  until the Pi sees home WiFi, no manual intervention to recover from a
  cold boot in the driveway.

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
├── obd-ev-wifi.conf.example     # per-participant WiFi (goes on SD boot partition)
├── src/obd_ev/
│   ├── main.py                  # entry point, paced by OBD
│   ├── obd_reader.py            # BLE OBD reader wrapper + retry
│   ├── ble_obd.py               # BLE ELM327 transport and PID decoding
│   ├── gps_reader.py            # gpsd client, threaded
│   ├── imu_reader.py            # MPU-6050, threaded, low-pass filtered
│   ├── logger.py                # CSV writer, device_id-tagged filenames
│   └── config.py                # YAML loader + env overrides
├── scripts/
│   ├── setup_pi.sh              # one-shot Pi provisioning
│   ├── image_setup.sh           # researcher: configure rclone
│   ├── firstboot_wifi.sh        # apply /boot WiFi config on first boot
│   └── upload.sh                # rclone upload, idempotent
├── systemd/
│   ├── obd-ev.service           # main logger
│   ├── obd-ev-firstboot.service # WiFi provisioning
│   ├── obd-ev-upload.service    # one-shot upload
│   └── obd-ev-upload.timer      # fires every 10 min
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

1. `obd-ev-firstboot.service` (one-shot) — reads
   `/boot/firmware/obd-ev-wifi.conf` and registers WiFi networks via
   NetworkManager.
2. `obd-ev.service` — connects to the BLE OBD adapter (retrying until the car
   starts), starts
   GPS and IMU threads, writes one CSV per drive named with the device id and
   timestamp.
3. `obd-ev-upload.timer` — every minute, attempts to upload pending CSVs
   via rclone. No-op if the participant is away from a configured WiFi network
   or if nothing is pending. Uploaded files move to `logs/uploaded/`.

## Cloud storage

Any rclone backend works (Box, Google Drive, Dropbox, S3…). Configured once
during imaging via `rclone config`. The remote name in `/etc/default/obd-ev`
must match what's in `rclone.conf` (default: `obd-ev`).

## Notes on data quality

- **Acceleration.** GPS speed-delta gives cleaner forward/braking acceleration
  than the IMU (no gravity / mounting-angle problem). The IMU is logged raw
  and is most useful for lateral G and bumps.
- **OBD coverage.** The BLE reader logs the configured core Mode 01 PIDs —
  see [docs/pid_reference.md](docs/pid_reference.md).
- **GPS cold start.** First fix can take 30s–2min. Mount with sky view.

## License

MIT — see [LICENSE](LICENSE).
