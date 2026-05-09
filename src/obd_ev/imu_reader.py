import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from .config import IMUConfig

log = logging.getLogger(__name__)

FIELDS = ["accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"]


@dataclass
class IMUSample:
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0


class IMUReader:
    """Background MPU-6050 sampler with simple per-axis low-pass filter."""

    def __init__(self, cfg: IMUConfig):
        self.cfg = cfg
        self._sample = IMUSample()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.cfg.enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            from mpu6050 import mpu6050
        except ImportError:
            log.error("mpu6050-raspberrypi not installed; IMU disabled")
            return

        try:
            sensor = mpu6050(self.cfg.i2c_address)
        except Exception as e:
            log.error("MPU-6050 init failed: %s", e)
            return

        period = 1.0 / max(1, self.cfg.sample_hz)
        a = self.cfg.lowpass_alpha
        f = IMUSample()

        while not self._stop.is_set():
            try:
                ac = sensor.get_accel_data()
                gy = sensor.get_gyro_data()
            except Exception as e:
                log.warning("IMU read error: %s", e)
                time.sleep(period)
                continue

            f.accel_x = a * ac["x"] + (1 - a) * f.accel_x
            f.accel_y = a * ac["y"] + (1 - a) * f.accel_y
            f.accel_z = a * ac["z"] + (1 - a) * f.accel_z
            f.gyro_x  = a * gy["x"] + (1 - a) * f.gyro_x
            f.gyro_y  = a * gy["y"] + (1 - a) * f.gyro_y
            f.gyro_z  = a * gy["z"] + (1 - a) * f.gyro_z

            with self._lock:
                self._sample = IMUSample(**vars(f))
            time.sleep(period)

    def latest(self) -> Dict[str, float]:
        with self._lock:
            s = self._sample
        return vars(s).copy()

    def stop(self) -> None:
        self._stop.set()
