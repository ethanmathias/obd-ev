import logging
from typing import Dict, List, Optional

import obd

from .config import OBDConfig

log = logging.getLogger(__name__)


class OBDReader:
    def __init__(self, cfg: OBDConfig):
        self.cfg = cfg
        self.connection: Optional[obd.OBD] = None
        self.commands: List[obd.OBDCommand] = []

    def connect(self) -> None:
        kwargs = dict(fast=self.cfg.fast, timeout=self.cfg.timeout,
                      baudrate=self.cfg.baudrate)
        if self.cfg.port:
            self.connection = obd.OBD(self.cfg.port, **kwargs)
        else:
            self.connection = obd.OBD(**kwargs)

        if not self.connection.is_connected():
            raise RuntimeError("OBD connection failed")

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
        return [c.name for c in self.commands]

    def close(self) -> None:
        if self.connection:
            self.connection.close()
