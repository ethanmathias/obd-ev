import logging
import time
from typing import Dict, List

from .ble_obd import BleOBDReader
from .config import OBDConfig

log = logging.getLogger(__name__)


class OBDReader:
    def __init__(self, cfg: OBDConfig):
        self.cfg = cfg
        self.reader = BleOBDReader(cfg)

    def connect(self) -> None:
        """Block until the BLE OBD adapter is reachable."""
        while True:
            try:
                self.reader.connect()
                return
            except Exception as exc:
                log.warning(
                    "BLE OBD not connected (%s), retrying in %ds",
                    exc,
                    self.cfg.reconnect_seconds,
                )
            time.sleep(self.cfg.reconnect_seconds)

    def read(self) -> Dict[str, float]:
        return self.reader.read()

    def field_names(self) -> List[str]:
        return self.reader.field_names()

    def close(self) -> None:
        self.reader.close()
