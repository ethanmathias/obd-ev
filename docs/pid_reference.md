# OBD-II PID reference

OBD-II standardises a set of "Mode 01" PIDs (SAE J1979). Only `0x00` is truly
mandatory — it's a bitmask of which other PIDs the ECU supports. Everything
else is optional, even though most modern cars implement a common subset.

The BLE reader logs the configured core PIDs below. If a vehicle does not
return a value for a PID, that field is left blank for that row.

## Core PIDs (configured by default)

These are nearly universal across 1996+ vehicles:

| Field name      | PID  | Description |
|-----------------|------|-------------|
| `RPM`           | 0x0C | Engine RPM |
| `SPEED`         | 0x0D | Vehicle speed (km/h) |
| `THROTTLE_POS`  | 0x11 | Throttle position (%) |
| `COOLANT_TEMP`  | 0x05 | Coolant temperature (°C) |
| `ENGINE_LOAD`   | 0x04 | Calculated engine load (%) |

## Common-but-not-guaranteed PIDs

These are good future additions, but are not logged by default:

- `MAF` (0x10) — mass air flow (g/s)
- `INTAKE_TEMP` (0x0F) — intake air temp (°C)
- `INTAKE_PRESSURE` (0x0B) — manifold pressure (kPa)
- `FUEL_LEVEL` (0x2F) — fuel tank level (%)
- `BAROMETRIC_PRESSURE` (0x33) — barometric pressure (kPa)
- `SHORT_FUEL_TRIM_1`, `LONG_FUEL_TRIM_1` (0x06, 0x07)
- `RUN_TIME` (0x1F) — time since engine start (s)
- `DISTANCE_W_MIL` (0x21) — distance with check-engine light on (km)

## Manufacturer-specific PIDs

Beyond Mode 01, manufacturers expose proprietary PIDs (often Mode 22) for
things like transmission temp, oil pressure, EV battery state, etc. These
vary by make/model and are not covered here. Useful sources:

- [OBDb](https://github.com/OBDb) — community database of per-vehicle signal sets
- The Equipment and Tool Institute (ETI) maintains the canonical commercial database
