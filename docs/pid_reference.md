# OBD-II PID reference

This is the **fallback** path, used when no vehicle profile is configured. With
`vehicle.signalset` set, the kit uses that model's OBDb command set instead,
which is far richer — see [deployment.md](deployment.md).

At connect the reader asks the ECU which PIDs it supports (`0100`, `0120`, …)
and polls only those. Unsupported fields stay blank, so the CSV schema is
stable across vehicles.

**Most of the classic Mode 01 set is combustion-specific and absent on a
battery EV.** `RPM`, `COOLANT_TEMP`, `ENGINE_LOAD` and `THROTTLE_POS` are kept
for hybrids and cross-checking, not because they carry EV information.

## Polled every cycle

| Field | PID | | EV? |
|---|---|---|---|
| `SPEED` | 0x0D | Vehicle speed (km/h) | yes |
| `HV_BATTERY_LIFE` | 0x5B | Hybrid/EV pack remaining life — the standardised SOC | yes |
| `CONTROL_MODULE_VOLTAGE` | 0x42 | Module supply voltage | yes |
| `ACCEL_PEDAL_D` / `_E` | 0x49, 0x4A | Accelerator pedal position | yes |
| `RELATIVE_ACCEL_POS` | 0x5A | Relative accelerator position | yes |
| `ACTUAL_TORQUE` | 0x62 | Actual engine/drive torque | often |
| `RPM` | 0x0C | Engine RPM | rarely |
| `ENGINE_LOAD` | 0x04 | Calculated engine load | rarely |
| `THROTTLE_POS` | 0x11 | Throttle position | rarely |

## Polled every `slow_every_n` cycles

`AMBIENT_AIR_TEMP` (0x46), `COOLANT_TEMP` (0x05), `RUN_TIME` (0x1F),
`ODOMETER` (0xA6), `BAROMETRIC_PRESSURE` (0x33), `FUEL_LEVEL` (0x2F).

Also defined and available to add: `INTAKE_TEMP` (0x0F), `MAF` (0x10),
`ENGINE_OIL_TEMP` (0x5C), `REFERENCE_TORQUE` (0x63).

## Manufacturer PIDs

Pack voltage and current, per-cell temperatures, SOC to 0.1%, regen power,
per-wheel speed and steering angle are Mode 22 parameters that vary by model.
[OBDb](https://github.com/OBDb) catalogues them; this project consumes those
signalsets directly. Diagnostic trouble codes (Mode 03) are **not** read.
