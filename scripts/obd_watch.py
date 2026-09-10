#!/usr/bin/env python3
"""Show the vehicle signals the logger is actually recording, live.

Reads the trip CSV the logger is writing rather than talking to the adapter,
because BLE allows only one connection -- a tool that opened its own would have
to stop `obd-ev` first, and then you would not be testing the real thing.

    scripts/obd_watch.py             # decoded signals, refreshing
    scripts/obd_watch.py --all       # include columns that are still empty
    scripts/obd_watch.py --once      # one snapshot and exit

Column names, units and groups come from the trip's own signals_*.csv, so this
reflects whatever profile the kit is running.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from obd_ev.venv import reexec_if_needed  # noqa: E402
reexec_if_needed()

from obd_ev import config as cfgmod  # noqa: E402

# Short unit labels; anything unlisted prints as-is.
UNITS = {
    "kilometersPerHour": "km/h", "milesPerHour": "mph", "metersPerSecond": "m/s",
    "metersPerSecondSquared": "m/s2", "percent": "%", "volts": "V",
    "millivolts": "mV", "amps": "A", "milliamps": "mA", "celsius": "C",
    "kilowatts": "kW", "watts": "W", "kilowattHours": "kWh", "rpm": "rpm",
    "newtonMeters": "Nm", "degrees": "deg", "seconds": "s", "kilometers": "km",
    "miles": "mi", "psi": "psi", "kilopascal": "kPa", "ampereHours": "Ah",
    "scalar": "", "unknown": "", "offon": "", "onoff": "", "noyes": "",
    "yesno": "", "hours": "h", "minutes": "min", "hertz": "Hz",
}


def newest_trip(log_dir: Path):
    """The trip folder the logger is writing into, and its open CSV."""
    current = log_dir / ".current"
    if current.exists():
        try:
            path = Path(current.read_text().strip())
            if path.exists():
                return path
        except OSError:
            pass
    drives = [p for p in log_dir.glob("*/drive_*.csv")
              if "uploaded" not in p.parts]
    return max(drives, key=lambda p: p.stat().st_mtime) if drives else None


def load_dictionary(trip_dir: Path):
    """column -> (readable name, unit label, group, source)."""
    out = {}
    for path in trip_dir.glob("signals*.csv"):
        with path.open() as fh:
            for row in csv.DictReader(fh):
                unit = row.get("unit", "")
                out[row["column"]] = (
                    row.get("name") or row["column"],
                    UNITS.get(unit, unit),
                    row.get("group", ""),
                    row.get("source", ""),
                )
        break
    return out


def fmt(value):
    try:
        f = float(value)
    except ValueError:
        return value
    return f"{f:g}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true",
                        help="also list signals with no value yet")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    args = parser.parse_args()

    cfg = cfgmod.load(args.config)
    log_dir = Path(cfg.logger.output_dir)

    path = newest_trip(log_dir)
    if path is None:
        print(f"No trip CSV under {log_dir}. Is obd-ev running?", file=sys.stderr)
        return 1
    meta = load_dictionary(path.parent)
    print(f"watching {path.name}  ({path.parent.name})")

    first_rows = first_time = None
    try:
        while True:
            with path.open() as fh:
                rows = list(csv.DictReader(fh))
            if not rows:
                time.sleep(args.interval)
                continue
            last = rows[-1]
            now = time.monotonic()
            if first_rows is None:
                first_rows, first_time = len(rows), now
            elapsed = now - first_time
            rate = ((len(rows) - first_rows) / elapsed) if elapsed > 1 else 0.0

            vehicle = [c for c, m in meta.items() if m[3] == "vehicle-obdb"] \
                or [c for c in last if c not in
                    ("timestamp", "t_mono", "device_id", "obd_connected")]
            live = [c for c in vehicle if (last.get(c) or "").strip()]

            print("\033[2J\033[H", end="")          # clear, home
            print(f"{path.parent.name}   row {len(rows)}   "
                  f"{rate:.2f} rows/s   "
                  f"{len(live)}/{len(vehicle)} signals reporting   "
                  f"obd_connected={last.get('obd_connected')}")
            print(f"{last.get('timestamp', '')}")
            print("-" * 68)
            if not live:
                print("  no vehicle signals yet -- adapter connected but the car"
                      "\n  is not answering. Check it is in READY.")
            for column in (vehicle if args.all else live):
                name, unit, group, _ = meta.get(column, (column, "", "", ""))
                value = (last.get(column) or "").strip()
                print(f"  {name[:38]:<38} {fmt(value) if value else '-':>10} "
                      f"{unit:<6} {group}")
            if args.once:
                break
            time.sleep(args.interval)
            # Follow a rotation into the next part.
            newer = newest_trip(log_dir)
            if newer is not None and newer != path:
                path = newer
                meta = load_dictionary(path.parent)
                first_rows = first_time = None
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
