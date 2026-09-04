"""Poll a known vehicle's OBDb command set over the BLE ELM327 link.

Generic Mode 01 gives roughly ten values that every car happens to share.
A vehicle-specific OBDb signalset gives the manufacturer's own Mode 22
parameters -- pack voltage and current, per-cell temperatures, true state of
charge, per-wheel speed, steering angle -- which is what an EV study actually
needs. Use this reader when the make/model/year is known at imaging time.

Wire format is `ATH1` + `ATCAF0`: the adapter prints raw CAN frames and this
module reassembles ISO-TP itself, which is the format OBDb's published test
vectors are recorded in (see tests/test_obdb.py).
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .ble_obd import BleElm327, Elm327Timeout, OBDLinkDown
from .config import OBDConfig, VehicleConfig
from .naming import assign_columns, group_of
from .obdb import Command, SignalSet

log = logging.getLogger(__name__)


@dataclass
class _Scheduled:
    command: Command
    period: float
    due_at: float = 0.0
    failures: int = 0
    disabled: bool = False

    @property
    def group(self) -> Tuple[str, str, bool]:
        """Commands sharing a group need no header reprogramming between them."""
        return (self.command.hdr or "", self.command.rax or "", self.command.fcm1)


class VehicleReader:
    """Schedules OBDb commands by their declared frequency and decodes replies."""

    def __init__(self, cfg: OBDConfig, vcfg: VehicleConfig, adapter=None):
        self.cfg = cfg
        self.vcfg = vcfg
        # `adapter` is an injection point for tests; production passes nothing.
        self.adapter = adapter or BleElm327(cfg, raw_frames=True)
        self.signalset = SignalSet.load(vcfg.signalset).for_year(vcfg.year)
        self._schedule = self._build_schedule()
        # Vendor signal id -> readable CSV column. Built once; signals.csv
        # carries the mapping back for anyone checking against OBDb.
        self.columns = assign_columns(
            (sig.id, sig.name, sig.fmt.unit)
            for item in self._schedule for sig in item.command.signals)
        self._group: Optional[Tuple[str, str, bool]] = None
        self._failures = 0
        log.info("loaded %s: %d commands, %d signals",
                 vcfg.signalset, len(self._schedule), len(self.field_names()))

    def _build_schedule(self) -> List[_Scheduled]:
        out = []
        for command in self.signalset.commands:
            if not command.signals:
                continue
            if self.vcfg.exclude_paths and any(
                    s.path.startswith(p) for s in command.signals
                    for p in self.vcfg.exclude_paths):
                continue
            if self.vcfg.include_paths and not any(
                    s.path.startswith(p) for s in command.signals
                    for p in self.vcfg.include_paths):
                continue
            period = max(command.freq or self.vcfg.default_period,
                         self.vcfg.min_period)
            out.append(_Scheduled(command, period))
        # Fastest first, then grouped by header so a busy cycle reprograms the
        # adapter as few times as possible.
        out.sort(key=lambda s: (s.period, s.group))
        if self.vcfg.max_commands:
            out = out[:self.vcfg.max_commands]
        return out

    def connect(self) -> None:
        self.adapter.connect()
        self.adapter.pin_protocol()
        self._group = None
        self._failures = 0
        now = time.monotonic()
        for item in self._schedule:
            item.due_at = now
            item.failures = 0
            item.disabled = False

    def field_names(self) -> List[str]:
        """Stable CSV schema: every signal this vehicle could report, whether
        or not the ECU answers on a given cycle.

        De-duplicated -- a signal can legitimately appear in two commands (year
        variants, or two ECUs reporting the same quantity), and a repeated
        column name would make the CSV ambiguous to whatever reads it later.
        """
        seen = set()
        names = []
        for item in self._schedule:
            for signal in item.command.signals:
                column = self.columns[signal.id]
                if column not in seen:
                    seen.add(column)
                    names.append(column)
        return names

    def describe(self) -> List[dict]:
        """Rows for signals.csv: one per column, carrying the readable name,
        unit, category, and the OBDb id and command it was decoded from."""
        rows = []
        seen = set()
        for item in self._schedule:
            for signal in item.command.signals:
                column = self.columns[signal.id]
                if column in seen:
                    continue
                seen.add(column)
                fmt = signal.fmt
                rows.append({
                    "column": column,
                    "name": signal.name,
                    "unit": fmt.unit,
                    "group": group_of(signal.path),
                    "category": signal.path,
                    "source": "vehicle-obdb",
                    "source_id": signal.id,
                    "command": item.command.request(),
                    "period_s": item.period,
                    "min": fmt.min if fmt.max > fmt.min else "",
                    "max": fmt.max if fmt.max > fmt.min else "",
                })
        return rows

    def _select_group(self, item: _Scheduled) -> None:
        """Point the adapter at this command's ECU. Skipped when the previous
        command already left it configured the same way."""
        if self._group == item.group:
            return
        cmd = item.command
        if cmd.hdr:
            self.adapter.command(f"ATSH{cmd.hdr}", timeout=2)
        if cmd.rax:
            self.adapter.command(f"ATCRA{cmd.rax}", timeout=2)
        if cmd.fcm1:
            # Manual flow control: answer the ECU's first frame ourselves so it
            # sends the remaining frames.
            self.adapter.command(f"ATFCSH{cmd.hdr or ''}", timeout=2)
            self.adapter.command("ATFCSD300000", timeout=2)
            self.adapter.command("ATFCSM1", timeout=2)
        else:
            self.adapter.command("ATFCSM0", timeout=2)
        self._group = item.group

    def _note_failure(self, item: _Scheduled) -> None:
        """Retire a command the vehicle never answers usefully, so the sample
        loop stops spending a round trip on it every cycle for weeks."""
        item.failures += 1
        if self.vcfg.disable_after and item.failures >= self.vcfg.disable_after:
            item.disabled = True
            log.info("retiring command %s after %d unanswered attempts",
                     item.command.key, item.failures)
            live = sum(1 for i in self._schedule if not i.disabled)
            log.info("%d of %d commands still active",
                     live, len(self._schedule))

    def read(self) -> Dict[str, object]:
        """Run every command that is due and return the decoded signals."""
        now = time.monotonic()
        due = [i for i in self._schedule if not i.disabled and i.due_at <= now]
        if not due:
            return {}

        out: Dict[str, object] = {}
        timeouts = 0
        for item in due:
            try:
                self._select_group(item)
                response = self.adapter.command(item.command.request())
            except Elm327Timeout:
                timeouts += 1
                self._note_failure(item)
                item.due_at = now + item.period
                continue

            decoded = item.command.decode_response(response)
            if decoded:
                item.failures = 0
                out.update({self.columns[k]: v for k, v in decoded.items()})
            else:
                # The usual shape of an unsupported command is a prompt reply
                # of "NO DATA", not a timeout, so this path -- not the one
                # above -- is what retires most dead commands.
                self._note_failure(item)
            item.due_at = now + item.period

        if out:
            # The vehicle is demonstrably awake, so retirements made while it
            # was answering are real and stand.
            self._failures = 0
        elif timeouts == len(due):
            self._failures += 1
            if self._failures >= self.cfg.max_read_failures:
                raise OBDLinkDown(
                    f"adapter silent for {self._failures} consecutive cycles")

        if all(i.disabled for i in self._schedule):
            # Nothing ever answered. Much the likeliest cause is that the car
            # was asleep when we connected -- every command returns NO DATA --
            # rather than the signalset being wrong for this vehicle. Retiring
            # the whole set permanently would mean collecting nothing for the
            # rest of the study, so reset and force a reconnect instead.
            log.warning("every command went unanswered; resetting the schedule "
                        "and reconnecting (was the vehicle asleep?)")
            for item in self._schedule:
                item.disabled = False
                item.failures = 0
            raise OBDLinkDown("no command answered on this connection")
        return out

    def close(self) -> None:
        self.adapter.close()
