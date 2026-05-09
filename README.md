# obd-ev

Raspberry Pi data logger for vehicles. Auto-connects to a Bluetooth ELM327 OBD-II
scanner and merges live OBD telemetry with GPS and IMU data into a single CSV
per drive.

## Hardware

| Component | Part | Interface | Pi pins |
|-----------|------|-----------|---------|
| OBD scanner | ELM327 Bluetooth | Bluetooth SPP | onboard radio |
| GPS | u-blox NEO-6M (GY-NEO6MV2) | UART | 3.3V, GND, GPIO14/15 |
| IMU | MPU-6050 (GY-521) | I2C | 3.3V, GND, GPIO2/3 |
| Host | Raspberry Pi 3A+ or newer | — | — |

Wiring details: see [docs/wiring.md](docs/wiring.md).

## What gets logged

Every row in the output CSV contains a timestamp plus the latest reading from
each sensor. The fields are:

- **OBD** — RPM, vehicle speed, throttle position, coolant temp, engine load,
  plus any additional PIDs the connected vehicle reports as supported.
- **GPS** — latitude, longitude, altitude, ground speed, heading, fix quality.
- **IMU** — accelerometer X/Y/Z (g), gyroscope X/Y/Z (deg/s).

OBD is the slowest source (~2–5 Hz depending on PID count), so the main loop
is locked to its cadence. GPS and IMU values are read at the loop tick from
the latest cached sample.

## Repo layout

```
obd-ev/
├── README.md
├── requirements.txt
├── config.yaml.example      # copy to config.yaml and edit
├── src/obd_ev/
│   ├── main.py              # entry point
│   ├── obd_reader.py        # python-obd wrapper, supported-PID discovery
│   ├── gps_reader.py        # gpsd client, runs in a thread
│   ├── imu_reader.py        # MPU-6050, runs in a thread w/ low-pass filter
│   ├── logger.py            # CSV writer
│   └── config.py            # config loader
├── scripts/
│   ├── setup_pi.sh          # one-shot Pi provisioning (apt, pip, raspi-config)
│   └── rfcomm_bind.sh       # bind the OBD adapter to /dev/rfcomm0
├── systemd/
│   └── obd-ev.service       # autostart on boot
└── docs/
    ├── wiring.md
    └── pid_reference.md
```

## Quickstart

On a fresh Raspberry Pi OS Lite install:

```bash
git clone <this repo> obd-ev
cd obd-ev
./scripts/setup_pi.sh           # installs deps, enables I2C/UART
sudo ./scripts/rfcomm_bind.sh AA:BB:CC:DD:EE:FF   # your ELM327 MAC
cp config.yaml.example config.yaml
python -m obd_ev.main
```

To autostart on boot:

```bash
sudo cp systemd/obd-ev.service /etc/systemd/system/
sudo systemctl enable --now obd-ev
```

## Configuration

`config.yaml` controls device paths, log location, sample rate, and which
optional PIDs to attempt. The defaults work for the wiring above.

## Notes on data quality

- **Acceleration.** Forward/braking acceleration is more accurate when derived
  from the GPS speed delta than from the MPU-6050 (no gravity / mounting-angle
  problem). The IMU is logged raw and is most useful for lateral G and bumps.
- **OBD support varies.** Only PID `0x00` is truly mandatory. The reader
  queries `supported_commands` on connect and only logs PIDs the vehicle
  actually responds to. See [docs/pid_reference.md](docs/pid_reference.md).
- **GPS cold start.** First fix can take 30s–2min after power-on. Mount with
  clear sky view.

## License

MIT — see [LICENSE](LICENSE).
