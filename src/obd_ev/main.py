import argparse
import logging
import signal
import sys
import time

from . import config as cfgmod
from .obd_reader import OBDReader
from .gps_reader import GPSReader, FIELDS as GPS_FIELDS
from .imu_reader import IMUReader, FIELDS as IMU_FIELDS
from .logger import CsvLogger


def main() -> int:
    parser = argparse.ArgumentParser(prog="obd-ev")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("obd_ev")

    cfg = cfgmod.load(args.config)

    obd_reader = OBDReader(cfg.obd)
    obd_reader.connect()

    gps_reader = GPSReader(cfg.gps)
    gps_reader.start()

    imu_reader = IMUReader(cfg.imu)
    imu_reader.start()

    fieldnames = ["device_id"] + obd_reader.field_names() + GPS_FIELDS + IMU_FIELDS
    csv_log = CsvLogger(cfg.logger, fieldnames, device_id=cfg.device.id)
    log.info("logging to %s as device_id=%s", csv_log.path, cfg.device.id)

    stop = False

    def _sig(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        while not stop:
            row = {"device_id": cfg.device.id}
            row.update(obd_reader.read())     # paces the loop
            row.update(gps_reader.latest())
            row.update(imu_reader.latest())
            csv_log.write(row)
    finally:
        gps_reader.stop()
        imu_reader.stop()
        obd_reader.close()
        csv_log.close()
        log.info("shutdown clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
