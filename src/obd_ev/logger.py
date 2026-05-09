import csv
import datetime as dt
import os
from pathlib import Path
from typing import Dict, List

from .config import LoggerConfig


class CsvLogger:
    def __init__(self, cfg: LoggerConfig, fieldnames: List[str]):
        self.cfg = cfg
        Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = Path(cfg.output_dir) / f"drive_{ts}.csv"
        self.fieldnames = ["timestamp"] + fieldnames
        self._fh = self.path.open("w", newline="")
        self._writer = csv.DictWriter(
            self._fh, fieldnames=self.fieldnames, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._n = 0

    def write(self, row: Dict) -> None:
        row = {**row, "timestamp": row.get("timestamp", dt.datetime.utcnow().isoformat())}
        self._writer.writerow(row)
        self._n += 1
        if self._n % self.cfg.flush_every == 0:
            self._fh.flush()
            os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()
