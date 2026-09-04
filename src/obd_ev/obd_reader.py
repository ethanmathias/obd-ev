"""Supervises the OBD link so the rest of the logger never blocks on it.

The adapter is unavailable for long stretches -- the car is off, the
participant unplugged the dongle, BLE dropped on a cold morning. None of that
should stop GPS and IMU from being recorded, and none of it should take the
process down and start a fresh CSV. So connection and reconnection happen on a
background thread while the sample loop keeps running.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .ble_obd import BleOBDReader, OBDLinkDown
from .config import Config, OBDConfig

log = logging.getLogger(__name__)


def build_reader(cfg: Config):
    """Vehicle-specific OBDb signalset when one is configured, else generic
    Mode 01. `scripts/fetch_signalset.py` vendors the former at imaging time.

    A missing or unreadable profile falls back to generic Mode 01 rather than
    taking the kit down: a typo in OBD_EV_VEHICLE should cost some vehicle
    signals, not the whole drive including GPS.
    """
    if not cfg.vehicle.signalset:
        return BleOBDReader(cfg.obd)

    if not Path(cfg.vehicle.signalset).exists():
        log.error("vehicle profile %s not found -- falling back to generic "
                  "Mode 01. Fetch it with scripts/fetch_signalset.py",
                  cfg.vehicle.signalset)
        return BleOBDReader(cfg.obd)
    try:
        from .vehicle import VehicleReader
        return VehicleReader(cfg.obd, cfg.vehicle)
    except Exception as exc:
        log.error("could not load vehicle profile %s (%s) -- falling back to "
                  "generic Mode 01", cfg.vehicle.signalset, exc)
        return BleOBDReader(cfg.obd)


class OBDLink:
    def __init__(self, cfg: OBDConfig, factory: Callable[[], object]):
        self.cfg = cfg
        self._factory = factory
        self._reader = factory()
        self._fields = list(self._reader.field_names())
        # Captured up front: the reader is rebuilt on reconnect, but the CSV
        # schema and its documentation must stay fixed for the whole run.
        self._descriptions = list(self._reader.describe())
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None
        self.connected_since: Optional[float] = None
        self.last_data_at: Optional[float] = None

    def field_names(self) -> List[str]:
        return self._fields

    def describe(self) -> List[dict]:
        return self._descriptions

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._supervise, daemon=True,
                                        name="obd-link")
        self._thread.start()

    def _supervise(self) -> None:
        while not self._stop.is_set():
            if not self._connected.is_set():
                self._try_connect()
            # Wake early when read() reports the link went down.
            self._wake.wait(timeout=self.cfg.reconnect_seconds)
            self._wake.clear()

    def _try_connect(self) -> None:
        with self._lock:
            if self._reader is None:
                try:
                    self._reader = self._factory()
                except Exception as exc:
                    self.last_error = str(exc)
                    log.warning("could not build OBD reader: %s", exc)
                    return
            reader = self._reader
        try:
            reader.connect()
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("OBD not connected (%s), retrying in %ds",
                        exc, self.cfg.reconnect_seconds)
            # The adapter object may be wedged; rebuild it next attempt.
            with self._lock:
                self._teardown_locked()
            return
        self.last_error = None
        self.connected_since = time.monotonic()
        self._connected.set()

    def _teardown_locked(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception as exc:
                log.debug("error closing OBD reader: %s", exc)
            self._reader = None

    def read(self) -> Dict[str, object]:
        """Sample the vehicle. Returns {} when the link is down, and flags the
        supervisor to reconnect if it goes down mid-read."""
        if not self._connected.is_set():
            return {}
        with self._lock:
            reader = self._reader
        if reader is None:
            return {}
        try:
            values = reader.read()
        except OBDLinkDown as exc:
            log.warning("OBD link down: %s", exc)
            self._drop()
            return {}
        except Exception as exc:
            log.warning("OBD read failed (%s); reconnecting", exc)
            self._drop()
            return {}
        if values:
            self.last_data_at = time.monotonic()
        return values

    def _drop(self) -> None:
        self._connected.clear()
        self.connected_since = None
        with self._lock:
            self._teardown_locked()
        self._wake.set()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._connected.clear()
        with self._lock:
            self._teardown_locked()
