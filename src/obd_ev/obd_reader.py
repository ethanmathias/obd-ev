import logging
from typing import Dict, List, Optional

import obd

from .ble_obd import BleOBDReader
from .config import OBDConfig

log = logging.getLogger(__name__)


class OBDReader:
    def __init__(self, cfg: OBDConfig):
        self.cfg = cfg
        self.ble_reader: Optional[BleOBDReader] = None
        self.connection: Optional[obd.OBD] = None
        self.commands: List[obd.OBDCommand] = []

    def connect(self) -> None:
        """Block until the OBD adapter is reachable. Retries forever — the Pi
        may boot before the car is started or before the BT link comes up."""
        import time
        if self.cfg.transport == "ble":
            self.ble_reader = BleOBDReader(self.cfg)
            while True:
                try:
                    self.ble_reader.connect()
                    return
                except Exception as exc:
                    log.warning(
                        "BLE OBD not connected (%s), retrying in %ds",
                        exc,
                        self.cfg.reconnect_seconds,
                    )
                    time.sleep(self.cfg.reconnect_seconds)

        kwargs = dict(fast=self.cfg.fast, timeout=self.cfg.timeout,
                      baudrate=self.cfg.baudrate)
        while True:
            if self.cfg.port:
                self.connection = obd.OBD(self.cfg.port, **kwargs)
            else:
                self.connection = obd.OBD(**kwargs)
            if self.connection.is_connected():
                break
            log.warning("OBD not connected, retrying in %ds", self.cfg.reconnect_seconds)
            time.sleep(self.cfg.reconnect_seconds)

        supported = set(self.connection.supported_commands)
        chosen: List[obd.OBDCommand] = []

        # Always-on core PIDs (only if the car supports them).
        for name in self.cfg.core_pids:
            cmd = getattr(obd.commands, name, None)
            if cmd is None:
                log.warning("Unknown core PID name: %s", name)
                continue
            if cmd in supported:
                chosen.append(cmd)
            else:
                log.warning("Vehicle does not support core PID %s", name)

        # Add every other supported command we haven't already picked up.
        for cmd in supported:
            if cmd not in chosen:
                chosen.append(cmd)

        self.commands = chosen
        log.info("OBD ready, %d commands subscribed", len(chosen))

    def read(self) -> Dict[str, float]:
        if self.ble_reader:
            return self.ble_reader.read()

        out: Dict[str, float] = {}
        if not self.connection or not self.connection.is_connected():
            return out
        for cmd in self.commands:
            r = self.connection.query(cmd)
            if r.is_null():
                continue
            v = r.value
            try:
                out[cmd.name] = float(v.magnitude)  # pint Quantity
            except AttributeError:
                # Non-numeric (status strings, bitfields). Stringify.
                out[cmd.name] = str(v)
        return out

    def field_names(self) -> List[str]:
        if self.ble_reader:
            return self.ble_reader.field_names()
        return [c.name for c in self.commands]

    def close(self) -> None:
        if self.ble_reader:
            self.ble_reader.close()
        if self.connection:
            self.connection.close()
