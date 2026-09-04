import asyncio
import logging
import re
import subprocess
import threading
from concurrent.futures import Future
from typing import (TYPE_CHECKING, Callable, Dict, List, NamedTuple, Optional,
                    Sequence, Set, Tuple)

from .naming import assign_columns

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - exercised on devices before setup reruns
    BleakClient = None
    BleakScanner = None

if TYPE_CHECKING:
    from .config import OBDConfig

log = logging.getLogger(__name__)


def _u16(b):
    return (b[0] * 256) + b[1]


class PidDef(NamedTuple):
    pid: int
    decode: Callable[[Sequence[int]], float]
    nbytes: int
    label: str          # human-readable, for signals.csv
    unit: str           # OBDb unit enum, so column suffixes match


# SAE J1979 Mode 01 PIDs. Vehicles answer only a subset; the reader probes
# support at connect and skips the rest, so listing extras costs nothing.
#
# The EV-relevant ones are 0x5B (pack state of charge), 0x42 (module
# voltage), 0x49/0x4A/0x5A (pedal demand) and 0x62 (actual torque). The
# classic ICE PIDs are kept for hybrids and for combustion control vehicles.
PID_DEFS = {
    "ENGINE_LOAD": PidDef(
        0x04, lambda b: b[0] * 100.0 / 255.0, 1, "Calculated engine load", "percent"),
    "COOLANT_TEMP": PidDef(
        0x05, lambda b: b[0] - 40.0, 1, "Coolant temperature", "celsius"),
    "RPM": PidDef(
        0x0C, lambda b: _u16(b) / 4.0, 2, "Engine speed", "rpm"),
    "SPEED": PidDef(
        0x0D, lambda b: float(b[0]), 1, "Vehicle speed", "kilometersPerHour"),
    "INTAKE_TEMP": PidDef(
        0x0F, lambda b: b[0] - 40.0, 1, "Intake air temperature", "celsius"),
    "MAF": PidDef(
        0x10, lambda b: _u16(b) / 100.0, 2, "Mass air flow", "gramsPerSecond"),
    "THROTTLE_POS": PidDef(
        0x11, lambda b: b[0] * 100.0 / 255.0, 1, "Throttle position", "percent"),
    "RUN_TIME": PidDef(
        0x1F, lambda b: float(_u16(b)), 2, "Run time since engine start", "seconds"),
    "FUEL_LEVEL": PidDef(
        0x2F, lambda b: b[0] * 100.0 / 255.0, 1, "Fuel tank level", "percent"),
    "BAROMETRIC_PRESSURE": PidDef(
        0x33, lambda b: float(b[0]), 1, "Barometric pressure", "kilopascal"),
    "CONTROL_MODULE_VOLTAGE": PidDef(
        0x42, lambda b: _u16(b) / 1000.0, 2, "Control module voltage", "volts"),
    "AMBIENT_AIR_TEMP": PidDef(
        0x46, lambda b: b[0] - 40.0, 1, "Ambient air temperature", "celsius"),
    "ACCEL_PEDAL_D": PidDef(
        0x49, lambda b: b[0] * 100.0 / 255.0, 1, "Accelerator pedal position D", "percent"),
    "ACCEL_PEDAL_E": PidDef(
        0x4A, lambda b: b[0] * 100.0 / 255.0, 1, "Accelerator pedal position E", "percent"),
    "RELATIVE_ACCEL_POS": PidDef(
        0x5A, lambda b: b[0] * 100.0 / 255.0, 1, "Relative accelerator position", "percent"),
    "HV_BATTERY_LIFE": PidDef(
        0x5B, lambda b: b[0] * 100.0 / 255.0, 1, "Hybrid/EV battery remaining life", "percent"),
    "ENGINE_OIL_TEMP": PidDef(
        0x5C, lambda b: b[0] - 40.0, 1, "Engine oil temperature", "celsius"),
    "ACTUAL_TORQUE": PidDef(
        0x62, lambda b: b[0] - 125.0, 1, "Actual engine torque", "percent"),
    "REFERENCE_TORQUE": PidDef(
        0x63, lambda b: float(_u16(b)), 2, "Reference engine torque", "newtonMeters"),
    "ODOMETER": PidDef(
        0xA6, lambda b: ((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) / 10.0,
        4, "Odometer", "kilometers"),
}

PROMPT = ">"

# Banks of the "PIDs supported" bitmask (Mode 01). Each answers 4 bytes
# covering the next 32 PIDs; the lowest bit says whether the next bank exists.
SUPPORT_BANKS = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0]


class Elm327Timeout(RuntimeError):
    """The adapter did not return a prompt within the command budget."""


class OBDLinkDown(RuntimeError):
    """The link is up but the adapter has stopped answering; reconnect."""


class BleElm327:
    def __init__(self, cfg: "OBDConfig", raw_frames: bool = False):
        self.cfg = cfg
        # raw_frames: print CAN headers and skip the adapter's own ISO-TP
        # assembly, so multi-frame Mode 22 answers can be reassembled here.
        # Required by the OBDb reader; the generic Mode 01 reader wants the
        # adapter's tidy formatting instead.
        self.raw_frames = raw_frames
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.client: Optional[BleakClient] = None
        self.write_uuid: Optional[str] = None
        self.notify_uuid: Optional[str] = None
        self.buffer = ""
        self.notify_event: Optional[asyncio.Event] = None
        self.thread.start()

    def connect(self) -> None:
        self._run(self._connect())

    def close(self) -> None:
        try:
            self._run(self._close())
        except Exception as exc:
            log.debug("error closing BLE link: %s", exc)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)

    def command(self, command: str, timeout: Optional[float] = None) -> str:
        return self._run(self._command(command, timeout or self.cfg.command_timeout))

    def pin_protocol(self) -> None:
        self._run(self._pin_protocol())

    def _run(self, coro):
        future: Future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    async def _connect(self) -> None:
        if BleakClient is None or BleakScanner is None:
            raise RuntimeError("BLE transport requires the 'bleak' Python package")

        if self.cfg.ble_address:
            log.info("connecting to BLE OBD adapter at %s", self.cfg.ble_address)
            subprocess.run(
                ["bluetoothctl", "disconnect", self.cfg.ble_address],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.client = BleakClient(self.cfg.ble_address, timeout=self.cfg.timeout)
            try:
                await self.client.connect()
            except Exception as exc:
                log.warning("direct BLE connect failed (%s), falling back to scan", exc)
                self.client = None

        if self.client is None:
            device = await BleakScanner.find_device_by_filter(
                lambda d, _: bool(d.name and self.cfg.ble_name.lower() in d.name.lower()),
                timeout=self.cfg.timeout,
            )
            if device is None:
                raise RuntimeError("BLE OBD adapter not found")
            log.info("connecting to BLE OBD adapter %s (%s)", device.name, device.address)
            self.client = BleakClient(device, timeout=self.cfg.timeout)
            await self.client.connect()

        self.write_uuid, self.notify_uuid = self._select_characteristics()
        self.notify_event = asyncio.Event()
        await self.client.start_notify(self.notify_uuid, self._on_notify)

        # ATZ resets the adapter and emits a version banner; give it room.
        await self._command("ATZ", timeout=8)
        headers = "ATH1" if self.raw_frames else "ATH0"
        auto_format = "ATCAF0" if self.raw_frames else "ATCAF1"
        for cmd in ["ATE0", "ATL0", "ATS0", headers, auto_format]:
            await self._command(cmd, timeout=3)
        # Adaptive timing lets the adapter return as soon as the ECU is done
        # instead of always waiting out the full response window.
        await self._command(f"ATAT{self.cfg.adaptive_timing}", timeout=3)
        await self._command(f"ATST{self.cfg.response_timeout}", timeout=3)
        await self._command("ATSP0", timeout=3)

    async def _pin_protocol(self) -> None:
        """Freeze the auto-detected protocol so later failures don't trigger a
        fresh (multi-second) protocol search on every command."""
        try:
            found = await self._command("ATDPN", timeout=3)
        except Elm327Timeout:
            return
        match = re.search(r"A?([0-9A-C])", found.strip().upper())
        if not match:
            return
        try:
            await self._command(f"ATSP{match.group(1)}", timeout=3)
            log.info("pinned OBD protocol to %s", match.group(1))
        except Elm327Timeout:
            log.debug("could not pin protocol, leaving auto-detect on")

    async def _close(self) -> None:
        if self.client and self.client.is_connected:
            if self.notify_uuid:
                try:
                    await self.client.stop_notify(self.notify_uuid)
                except Exception:
                    pass
            await self.client.disconnect()

    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    def _select_characteristics(self) -> Tuple[str, str]:
        if not self.client:
            raise RuntimeError("BLE client is not connected")

        chars = [c for service in self.client.services for c in service.characteristics]
        by_uuid = {c.uuid.lower(): c for c in chars}

        write_uuid = self.cfg.ble_write_uuid
        notify_uuid = self.cfg.ble_notify_uuid
        if write_uuid and notify_uuid:
            return write_uuid, notify_uuid

        notify_chars = [c for c in chars if "notify" in c.properties]
        write_chars = [
            c for c in chars
            if "write" in c.properties or "write-without-response" in c.properties
        ]

        # Common VEEPEAK / BLE ELM327 UART-style characteristic pairs.
        preferred_pairs = [
            ("0000fff2-0000-1000-8000-00805f9b34fb", "0000fff1-0000-1000-8000-00805f9b34fb"),
            ("0000fff1-0000-1000-8000-00805f9b34fb", "0000fff2-0000-1000-8000-00805f9b34fb"),
            ("000069fe-0000-1000-8000-00805f9b34fb", "00000318-0000-1000-8000-00805f9b34fb"),
            ("00000318-0000-1000-8000-00805f9b34fb", "000069fe-0000-1000-8000-00805f9b34fb"),
        ]
        for write, notify in preferred_pairs:
            if not write_uuid and write in by_uuid and by_uuid[write] in write_chars:
                write_uuid = write
            if not notify_uuid and notify in by_uuid and by_uuid[notify] in notify_chars:
                notify_uuid = notify
            if write_uuid and notify_uuid:
                return write_uuid, notify_uuid

        if not write_uuid and write_chars:
            write_uuid = write_chars[0].uuid
        if not notify_uuid and notify_chars:
            notify_uuid = notify_chars[0].uuid
        if not write_uuid or not notify_uuid:
            raise RuntimeError("could not find BLE write/notify characteristics")
        log.info("BLE OBD write=%s notify=%s", write_uuid, notify_uuid)
        return write_uuid, notify_uuid

    def _on_notify(self, _sender, data: bytearray) -> None:
        text = bytes(data).decode(errors="ignore")
        self.buffer += text
        if self.notify_event and PROMPT in self.buffer:
            self.notify_event.set()

    async def _command(self, command: str, timeout: Optional[float] = None) -> str:
        if not self.client or not self.write_uuid or not self.notify_event:
            raise RuntimeError("BLE OBD adapter is not connected")
        budget = timeout or self.cfg.command_timeout
        self.buffer = ""
        self.notify_event.clear()
        await self.client.write_gatt_char(
            self.write_uuid, (command.strip() + "\r").encode(), response=False
        )
        try:
            await asyncio.wait_for(self.notify_event.wait(), timeout=budget)
        except asyncio.TimeoutError:
            # Let any straggling notification land, then drop it, so the next
            # command doesn't read this one's tail as its own response.
            await asyncio.sleep(0.05)
            self.buffer = ""
            self.notify_event.clear()
            raise Elm327Timeout(f"no response to {command} within {budget:.1f}s")
        return _clean_response(self.buffer, command)


def _clean_response(raw: str, command: str) -> str:
    text = raw.replace("\r", "\n").replace(PROMPT, "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(line for line in lines if line.upper() != command.upper())


def parse_pid_response(response: str, pid: int, needed: int) -> Optional[List[int]]:
    """Pull the data bytes out of a Mode 01 response. `41 0C 1A F8` -> [26, 248]."""
    if "NODATA" in re.sub(r"\s", "", response).upper():
        return None
    payload = re.sub(r"[^0-9A-Fa-f]", "", response).upper()
    marker = f"41{pid:02X}"
    idx = payload.find(marker)
    if idx < 0:
        return None
    data = payload[idx + len(marker):]
    if len(data) < needed * 2:
        return None
    return [int(data[i:i + 2], 16) for i in range(0, needed * 2, 2)]


def decode_support_mask(data: Sequence[int], base: int) -> Set[int]:
    """A support bank answers 4 bytes; the high bit of byte 0 is PID base+1."""
    supported = set()
    for i, byte in enumerate(data[:4]):
        for bit in range(8):
            if byte & (0x80 >> bit):
                supported.add(base + i * 8 + bit + 1)
    return supported


class BleOBDReader:
    def __init__(self, cfg: "OBDConfig"):
        self.cfg = cfg
        self.adapter = BleElm327(cfg)
        self.core = [n for n in cfg.core_pids if n in PID_DEFS]
        self.slow = [n for n in cfg.slow_pids if n in PID_DEFS]
        for name in set(cfg.core_pids + cfg.slow_pids) - set(PID_DEFS):
            log.warning("unknown PID %r in config, ignoring", name)
        self.columns = assign_columns(
            (n, PID_DEFS[n].label, PID_DEFS[n].unit) for n in self.core + self.slow)
        self.supported: Optional[Set[int]] = None
        self._cycle = 0
        self._failures = 0

    def connect(self) -> None:
        self.adapter.connect()
        self.adapter.pin_protocol()
        self._cycle = 0
        self._failures = 0
        self.supported = self._probe_supported() if self.cfg.probe_supported else None
        if self.supported is not None:
            live = [n for n in self.core + self.slow
                    if PID_DEFS[n].pid in self.supported]
            missing = [n for n in self.core + self.slow if n not in live]
            log.info("OBD ready: %d/%d configured PIDs supported by this vehicle",
                     len(live), len(self.core) + len(self.slow))
            if missing:
                log.info("vehicle does not report: %s", ", ".join(missing))
        else:
            log.info("OBD ready, polling all %d configured PIDs unprobed",
                     len(self.core) + len(self.slow))

    def _probe_supported(self) -> Optional[Set[int]]:
        supported: Set[int] = set()
        for base in SUPPORT_BANKS:
            try:
                response = self.adapter.command(f"01{base:02X}", timeout=3)
            except Elm327Timeout:
                log.warning("PID support probe timed out at bank %02X", base)
                break
            data = parse_pid_response(response, base, 4)
            if data is None:
                break
            supported |= decode_support_mask(data, base)
            # The last bit of a bank flags whether the next bank exists.
            if (base + 0x20) not in supported:
                break
        if not supported:
            log.warning("vehicle returned no PID support mask; polling everything")
            return None
        return supported

    def _due(self) -> List[str]:
        names = list(self.core)
        if self.cfg.slow_every_n > 0 and self._cycle % self.cfg.slow_every_n == 0:
            names += self.slow
        if self.supported is None:
            return names
        return [n for n in names if PID_DEFS[n].pid in self.supported]

    def read(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        timeouts = 0
        due = self._due()
        for name in due:
            spec = PID_DEFS[name]
            try:
                response = self.adapter.command(f"01{spec.pid:02X}")
            except Elm327Timeout:
                timeouts += 1
                continue
            data = parse_pid_response(response, spec.pid, spec.nbytes)
            if data is None:
                continue
            try:
                out[self.columns[name]] = spec.decode(data)
            except (IndexError, ValueError) as exc:
                log.debug("could not decode %s from %r: %s", name, response, exc)
        self._cycle += 1

        # A wedged adapter answers nothing at all; a merely unsupported PID
        # answers "NO DATA" quickly. Only the former should force a reconnect.
        if due and timeouts == len(due):
            self._failures += 1
            if self._failures >= self.cfg.max_read_failures:
                raise OBDLinkDown(
                    f"adapter silent for {self._failures} consecutive cycles")
        else:
            self._failures = 0
        return out

    def field_names(self) -> List[str]:
        """Every configured PID, supported or not, so the CSV schema is stable
        across vehicles and across reconnects mid-drive."""
        return [self.columns[n] for n in self.core + self.slow]

    def describe(self) -> List[dict]:
        """Rows for signals.csv, so every column in the CSV is documented."""
        rows = []
        for name in self.core + self.slow:
            spec = PID_DEFS[name]
            rows.append({
                "column": self.columns[name],
                "name": spec.label,
                "unit": spec.unit,
                "group": "OBD",
                "category": "OBD",
                "source": "obd-mode01",
                "source_id": name,
                "command": f"01{spec.pid:02X}",
                "period_s": "" if name in self.core else self.cfg.slow_every_n,
            })
        return rows

    def close(self) -> None:
        self.adapter.close()
