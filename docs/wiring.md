# Wiring

Pin numbers below refer to the physical 40-pin header on the Pi (board numbering),
with GPIO numbers in parentheses.

## GPS — GY-NEO6MV2

| GPS pin | Pi pin |
|---------|--------|
| VCC     | 1 (3.3V) |
| GND     | 6 (GND) |
| TX      | 10 (GPIO15 / RXD) |
| RX      | 8  (GPIO14 / TXD) |

The serial console must be disabled for the UART to be available — `setup_pi.sh`
handles this via `raspi-config nonint do_serial 2`.

Device path: `/dev/ttyAMA0` (or `/dev/serial0`). gpsd is configured to read
from there.

## IMU — GY-521 (MPU-6050)

| IMU pin | Pi pin |
|---------|--------|
| VCC     | 1 (3.3V) |
| GND     | 9 (GND) |
| SDA     | 3 (GPIO2 / SDA1) |
| SCL     | 5 (GPIO3 / SCL1) |

I2C address is `0x68` by default. Verify with:

```bash
i2cdetect -y 1
```

You should see a device at `68`.

## OBD scanner

BLE ELM327 over Bluetooth LE — no GPIO wiring. Set the adapter MAC in
`config.yaml` as `obd.ble_address`, or leave it blank to discover by
`obd.ble_name`.

## Power

In the car, use a USB-C PD supply rated for **5A** for the Pi 5.
Underpowered Pis will exhibit Bluetooth dropouts that look like OBD bugs.
