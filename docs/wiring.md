# Wiring

Pin numbers are physical positions on the 40-pin header.

## GPS — GY-NEO6MV2

| GPS | Pi pin |
|-----|--------|
| VCC | 1 (3.3V) |
| GND | 6 |
| TX  | 10 (GPIO15 / RXD) |
| RX  | 8 (GPIO14 / TXD) |

**The device path differs by board**, and getting it wrong looks exactly like a
dead GPS. `setup_pi.sh` picks it for you; this is what it picks and why.

| Board | GPS device | Notes |
|---|---|---|
| Pi 4 and earlier | `/dev/ttyS0` | the mini UART. `/dev/serial0` points here |
| Pi 5 | `/dev/ttyAMA0` | needs `dtparam=uart0=on` in config.txt, plus a reboot |

On Pi 4 the PL011 is taken by **Bluetooth** (it enumerates as `ttyAMA1`), so
GPIO14/15 gets the mini UART. Leave it that way — the OBD adapter is BLE, and
freeing the PL011 with `dtoverlay=disable-bt` would cost you the adapter.
`enable_uart=1` also pins the core clock, which is what makes the mini UART's
baud rate stable.

On Pi 5 the console lives on the separate debug connector, so `enable_uart=1`
evicts nothing and the header UART must be switched on explicitly. `dtparam=uart0=on`
is a no-op on Pi 4.

If the GPS is silent, check which device actually exists:

```bash
ls -l /dev/serial* /dev/ttyS* /dev/ttyAMA*
grep DEVICES /etc/default/gpsd
```

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
