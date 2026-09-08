#!/usr/bin/env python3
"""Print live GPS and IMU readings, to check the sensors are actually working.

Uses the same reader classes the logger uses, so a clean run here means the
logging path works -- not merely that something is wired to the bus.

    scripts/sensors.py              # both, once a second, Ctrl-C to stop
    scripts/sensors.py --gps        # GPS only
    scripts/sensors.py --imu        # IMU only
    scripts/sensors.py --once       # one reading and exit
    scripts/sensors.py --hz 5       # faster
"""

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from obd_ev.venv import in_venv, reexec_if_needed, venv_dir  # noqa: E402
reexec_if_needed()                           # mpu6050/bleak live in .venv

if venv_dir().exists() and not in_venv():
    print(f"WARNING: running under {sys.executable}, not the project venv at\n"
          f"         {venv_dir()}. Packages installed there (mpu6050, bleak)\n"
          f"         will look missing. Try: {venv_dir()}/bin/python "
          f"scripts/sensors.py", file=sys.stderr)

from obd_ev import config as cfgmod          # noqa: E402
from obd_ev.gps_reader import GPSReader      # noqa: E402
from obd_ev.imu_reader import IMUReader      # noqa: E402

FIX = {0: "none", 1: "none", 2: "2D", 3: "3D"}


def gps_line(sample):
    fix = FIX.get(sample.get("fix_mode") or 0, "?")
    used = sample.get("gps_sats_used") or 0
    visible = sample.get("gps_sats_visible") or 0
    snr = sample.get("gps_snr_max") or 0
    age = sample.get("gps_age_s")
    # used/visible together say much more than either alone: 0/16 means the
    # antenna hears plenty but has locked none, 0/0 means it hears nothing.
    counts = f"sats={used}/{visible} snr={snr:<4.1f}"

    lat, lon = sample.get("lat"), sample.get("lon")
    if lat is None or lon is None:
        hint = "" if visible else "   (antenna hears nothing)"
        return f"GPS  fix={fix:<4} {counts}  no position yet{hint}   age {age}s"

    alt = sample.get("alt")
    speed = sample.get("speed_gps")
    # A fix no satellite is marked as contributing to is not one to trust.
    weak = "  WEAK" if used == 0 else ""
    return (f"GPS  fix={fix:<4} {counts}  {lat:.6f}, {lon:.6f}"
            f"  alt {'?' if alt is None else round(alt, 1)}m"
            f"  speed {'?' if speed is None else round(speed, 2)} m/s"
            f"  age {age}s{weak}")


def imu_line(sample):
    if not sample.get("imu_samples"):
        return "IMU  no samples -- sensor not responding"
    return ("IMU  accel {accel_x:6.2f} {accel_y:6.2f} {accel_z:6.2f} m/s2"
            "   gyro {gyro_x:6.2f} {gyro_y:6.2f} {gyro_z:6.2f} deg/s"
            "   |a|max {accel_mag_max:5.2f}  n={imu_samples}").format(**sample)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gps", action="store_true", help="GPS only")
    parser.add_argument("--imu", action="store_true", help="IMU only")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    args = parser.parse_args()

    want_gps = args.gps or not args.imu
    want_imu = args.imu or not args.gps

    # Errors from the readers (missing module, no I2C device) are the whole
    # point of running this, so let them through.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = cfgmod.load(args.config)
    gps = imu = None
    if want_gps:
        cfg.gps.enabled = True                # this is a hardware check
        gps = GPSReader(cfg.gps)
        gps.start()
    if want_imu:
        cfg.imu.enabled = True
        imu = IMUReader(cfg.imu)
        imu.start()

    if want_gps:
        print("Waiting for gpsd... a cold start takes 30s-2min and needs sky view.",
              flush=True)
    period = 1.0 / max(args.hz, 0.01)
    try:
        while True:
            time.sleep(period)
            stamp = time.strftime("%H:%M:%S")
            # flush: stdout is block-buffered when piped or redirected, so
            # without this the tool looks dead under `| head`, `tee`, or
            # `timeout`, which kills it before anything is written.
            if gps is not None:
                print(f"{stamp}  {gps_line(gps.latest())}", flush=True)
            if imu is not None:
                print(f"{stamp}  {imu_line(imu.latest())}", flush=True)
            if args.once:
                break
    except KeyboardInterrupt:
        print()
    finally:
        if gps is not None:
            gps.stop()
        if imu is not None:
            imu.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
