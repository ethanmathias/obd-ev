# Wiring

Pin numbers are physical positions on the 40-pin header.

## GPS — GY-NEO6MV2

| GPS | Pi pin |
|-----|--------|
| VCC | 1 (3.3V) |
| GND | 6 |
| TX  | 10 (GPIO15 / RXD) |
| RX  | 8 (GPIO14 / TXD) |

Device path on Pi 5 is `/dev/ttyAMA0`. Do **not** use `/dev/serial0` — on Pi 5
it can point at the debug UART instead of the header. `setup_kit.sh` disables
the serial console for you.

## IMU — GY-521 (MPU-6050)

| IMU | Pi pin |
|-----|--------|
| VCC | 1 (3.3V) |
| GND | 9 |
| SDA | 3 (GPIO2) |
| SCL | 5 (GPIO3) |

Verify with `i2cdetect -y 1` — expect a device at `68`.

## OBD scanner

BLE, no wiring. Pin the adapter MAC as `obd.ble_address` in `config.yaml` for
faster, more reliable connects, or leave it null to discover by `obd.ble_name`.

## Power

Use a 5V **5A** USB-C supply. Underpowered Pi 5s show Bluetooth dropouts that
look like OBD bugs.

On most cars power is cut the instant the ignition goes off, so files are never
closed cleanly. The logger flushes every 10 rows or 2 seconds to bound the loss,
but only a UPS HAT prevents filesystem corruption over months of hard cuts.
