import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from .config import GPSConfig

log = logging.getLogger(__name__)

FIELDS = ["lat", "lon", "alt", "speed_gps", "heading", "fix_mode"]


@dataclass
class GPSSample:
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    speed_gps: Optional[float] = None  # m/s
    heading: Optional[float] = None    # degrees
    fix_mode: int = 0                  # 0=no fix, 2=2D, 3=3D


class GPSReader:
    """Background gpsd client. Latest sample is read via .latest()."""

    def __init__(self, cfg: GPSConfig):
        self.cfg = cfg
        self._sample = GPSSample()
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
            from gps import gps, WATCH_ENABLE, WATCH_NEWSTYLE
        except ImportError:
            log.error("python-gps not installed; GPS disabled")
            return

        try:
            session = gps(host=self.cfg.host, port=str(self.cfg.port),
                          mode=WATCH_ENABLE | WATCH_NEWSTYLE)
        except Exception as e:
            log.error("gpsd connect failed: %s", e)
            return

        while not self._stop.is_set():
            try:
                report = session.next()
            except StopIteration:
                break
            except Exception as e:
                log.warning("gpsd read error: %s", e)
                continue

            if getattr(report, "class", None) != "TPV":
                continue

            s = GPSSample(
                lat=getattr(report, "lat", None),
                lon=getattr(report, "lon", None),
                alt=getattr(report, "alt", None),
                speed_gps=getattr(report, "speed", None),
                heading=getattr(report, "track", None),
                fix_mode=getattr(report, "mode", 0),
            )
            with self._lock:
                self._sample = s

    def latest(self) -> Dict[str, Optional[float]]:
        with self._lock:
            s = self._sample
        return {
            "lat": s.lat,
            "lon": s.lon,
            "alt": s.alt,
            "speed_gps": s.speed_gps,
            "heading": s.heading,
            "fix_mode": s.fix_mode,
        }

    def stop(self) -> None:
        self._stop.set()
