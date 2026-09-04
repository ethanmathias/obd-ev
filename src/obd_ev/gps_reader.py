import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from .config import GPSConfig

log = logging.getLogger(__name__)

FIELDS = ["lat", "lon", "alt", "speed_gps", "heading", "fix_mode",
          "gps_sats", "gps_time", "gps_age_s"]

# Column documentation for signals.csv.
DESCRIPTIONS = [
    ("lat", "Latitude", "degrees"),
    ("lon", "Longitude", "degrees"),
    ("alt", "Altitude above mean sea level", "meters"),
    ("speed_gps", "Ground speed from GPS", "metersPerSecond"),
    ("heading", "Course over ground", "degrees"),
    ("fix_mode", "Fix quality: 0=none, 1=no fix, 2=2D, 3=3D", "scalar"),
    ("gps_sats", "Satellites used in the fix", "scalar"),
    ("gps_time", "Receiver UTC, independent of the Pi clock", "unknown"),
    ("gps_age_s", "Age of this fix when the row was written", "seconds"),
]


@dataclass
class GPSSample:
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    speed_gps: Optional[float] = None  # m/s
    heading: Optional[float] = None    # degrees
    fix_mode: int = 0                  # 0=no fix, 2=2D, 3=3D
    gps_time: Optional[str] = None     # receiver UTC, independent of the Pi clock
    t: float = field(default_factory=time.monotonic)


class GPSReader:
    """Background gpsd client. Latest sample is read via .latest()."""

    def __init__(self, cfg: GPSConfig):
        self.cfg = cfg
        self._sample = GPSSample()
        self._sats = 0
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

            kind = getattr(report, "class", None)
            if kind == "SKY":
                # Satellites used is the honest signal-quality number; a fix
                # can persist on stale ephemeris long after the sky is lost.
                sats = getattr(report, "satellites", None) or []
                with self._lock:
                    self._sats = sum(1 for s in sats if getattr(s, "used", False))
                continue
            if kind != "TPV":
                continue

            s = GPSSample(
                lat=getattr(report, "lat", None),
                lon=getattr(report, "lon", None),
                alt=getattr(report, "alt", None),
                speed_gps=getattr(report, "speed", None),
                heading=getattr(report, "track", None),
                fix_mode=getattr(report, "mode", 0),
                gps_time=getattr(report, "time", None),
            )
            with self._lock:
                self._sample = s

    def latest(self) -> Dict[str, Optional[float]]:
        with self._lock:
            s = self._sample
            sats = self._sats
        return {
            "lat": s.lat,
            "lon": s.lon,
            "alt": s.alt,
            "speed_gps": s.speed_gps,
            "heading": s.heading,
            "fix_mode": s.fix_mode,
            "gps_sats": sats,
            "gps_time": s.gps_time,
            # How old this fix is. Without it a row silently repeats the last
            # good position for as long as the receiver is blocked.
            "gps_age_s": round(time.monotonic() - s.t, 2),
        }

    def has_fix(self) -> bool:
        with self._lock:
            return self._sample.fix_mode >= 2

    def stop(self) -> None:
        self._stop.set()
