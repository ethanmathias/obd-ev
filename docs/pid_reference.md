# OBD-II PID reference

OBD-II standardises a set of "Mode 01" PIDs (SAE J1979). Only `0x00` is truly
mandatory — it's a bitmask of which other PIDs the ECU supports. Everything
else is optional, even though most modern cars implement a common subset.

**This page describes the fallback path.** When `vehicle.signalset` is
configured the logger uses that vehicle's OBDb command set instead, which is
far richer — see "Manufacturer-specific PIDs" below. Mode 01 is what runs when
the make/model is unknown.

At connect the reader asks the ECU which PIDs it supports (`0100`, `0120`, ...)
and polls only those, so listing a PID the vehicle lacks costs nothing. Fields
for unsupported PIDs stay blank, keeping the CSV schema stable across vehicles.

## A warning about EVs

Most of the classic Mode 01 set is combustion-specific and simply absent on a
battery EV. `RPM`, `COOLANT_TEMP`, `ENGINE_LOAD` and `THROTTLE_POS` are the
first things people log and among the least useful here. They are kept for
hybrids and for cross-checking, not because they carry EV information.

## Core PIDs (polled every cycle)

| Field name                | PID  | Description | EV? |
|---------------------------|------|-------------|-----|
| `SPEED`                   | 0x0D | Vehicle speed (km/h) | yes |
| `HV_BATTERY_LIFE`         | 0x5B | Hybrid/EV pack remaining life (%) — the standardised SOC | yes |
| `CONTROL_MODULE_VOLTAGE`  | 0x42 | Module supply voltage (V) | yes |
| `ACCEL_PEDAL_D`           | 0x49 | Accelerator pedal position D (%) | yes |
| `ACCEL_PEDAL_E`           | 0x4A | Accelerator pedal position E (%) | yes |
| `RELATIVE_ACCEL_POS`      | 0x5A | Relative accelerator position (%) | yes |
| `ACTUAL_TORQUE`           | 0x62 | Actual engine/drive torque (%) | often |
| `RPM`                     | 0x0C | Engine RPM | rarely |
| `ENGINE_LOAD`             | 0x04 | Calculated engine load (%) | rarely |
| `THROTTLE_POS`            | 0x11 | Throttle position (%) | rarely |

## Slow PIDs (polled every `slow_every_n` cycles)

Values that barely move, so they don't deserve a round trip every cycle.

| Field name              | PID  | Description |
|-------------------------|------|-------------|
| `AMBIENT_AIR_TEMP`      | 0x46 | Ambient air temperature (°C) |
| `COOLANT_TEMP`          | 0x05 | Coolant temperature (°C) |
| `RUN_TIME`              | 0x1F | Time since engine start (s) |
| `ODOMETER`              | 0xA6 | Odometer (km) |
| `BAROMETRIC_PRESSURE`   | 0x33 | Barometric pressure (kPa) |
| `FUEL_LEVEL`            | 0x2F | Fuel tank level (%) |

Also defined and available to add to either list: `INTAKE_TEMP` (0x0F),
`MAF` (0x10), `ENGINE_OIL_TEMP` (0x5C), `REFERENCE_TORQUE` (0x63).

## Manufacturer-specific PIDs

This is where EV data actually lives: pack voltage and current, per-cell
voltages and temperatures, true state of charge to 0.1%, charge and regen
power, per-wheel speed, steering angle. These are Mode 22 parameters that vary
by make and model.

[OBDb](https://github.com/OBDb) is a community database of exactly these, one
repo per vehicle. This project consumes those signalsets directly:

```bash
scripts/fetch_signalset.py --list ioniq
scripts/fetch_signalset.py Hyundai-IONIQ-5 --year 2024 --summary
```

A 2024 IONIQ 5 profile carries 33 commands and 381 signals. The decoder is
validated against OBDb's own published test vectors (191,994 signal values
across 8 EV models); see `scripts/validate_obdb.py` and `tests/test_obdb.py`.

The Equipment and Tool Institute (ETI) maintains the canonical commercial
database if a vehicle is missing from OBDb.
