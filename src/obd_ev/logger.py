import csv
import datetime as dt
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import LoggerConfig
from .naming import DICTIONARY_FIELDS

log = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_signal_dictionary(output_dir, rows: List[Dict], device_id: str = "") -> Path:
    """Write signals.csv: one row per CSV column, saying what it is.

    Every uploaded trip file is wide and machine-named; this is what makes it
    reviewable without reading the code or the vendor signalset. Written once
    per run and uploaded alongside the logs.
    """
    tag = f"_{device_id}" if device_id else ""
    path = Path(output_dir) / f"signals{tag}.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=DICTIONARY_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in DICTIONARY_FIELDS})
    log.info("wrote %s (%d columns documented)", path, len(rows))
    return path


class CsvLogger:
    """One CSV per trip segment.

    Rotation is not just hygiene: `upload.sh` never uploads the file the logger
    is currently writing, so a file that is never closed is never uploaded. A
    kit powered from an always-live OBD port would otherwise accumulate one
    enormous CSV and upload nothing at all.
    """

    def __init__(self, cfg: LoggerConfig, fieldnames: List[str], device_id: str = ""):
        self.cfg = cfg
        self.device_id = device_id
        self.dir = Path(cfg.output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fieldnames = ["timestamp", "t_mono"] + fieldnames
        self._fh = None
        self._writer = None
        self.path: Optional[Path] = None
        self._n = 0
        self._opened_at = 0.0
        self.open()

    def _next_path(self) -> Path:
        # device_id in the filename keeps uploads from many participants from
        # colliding in the shared cloud folder.
        tag = f"_{self.device_id}" if self.device_id else ""
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.dir / f"drive{tag}_{stamp}.csv"
        # A rotation inside the same second, or a clock that has not been set
        # yet, must not overwrite the file we just closed.
        seq = 1
        while path.exists():
            path = self.dir / f"drive{tag}_{stamp}_{seq}.csv"
            seq += 1
        return path

    def open(self) -> None:
        self.path = self._next_path()
        self._fh = self.path.open("w", newline="")
        self._writer = csv.DictWriter(
            self._fh, fieldnames=self.fieldnames, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._fh.flush()
        self._n = 0
        self._opened_at = time.monotonic()
        log.info("logging to %s", self.path)

    def write(self, row: Dict) -> None:
        row.setdefault("timestamp", utc_now_iso())
        row.setdefault("t_mono", round(time.monotonic(), 3))
        self._writer.writerow(row)
        self._n += 1
        if self._n % self.cfg.flush_every == 0:
            self._fh.flush()
            os.fsync(self._fh.fileno())

    @property
    def rows(self) -> int:
        return self._n

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self._opened_at

    def rotate(self) -> None:
        """Close the current segment and start a new one. The closed file
        becomes eligible for upload on the next timer tick."""
        empty = self._n == 0
        closing = self.path
        self.close()
        if empty and closing is not None:
            # Nothing was recorded; don't ship a header-only file.
            closing.unlink(missing_ok=True)
        self.open()

    def close(self) -> None:
        if self._fh is None:
            return
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        self._fh = None
        self._writer = None
