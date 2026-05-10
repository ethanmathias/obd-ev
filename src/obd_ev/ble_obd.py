import asyncio
import logging
import re
import threading
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - exercised on devices before setup reruns
    BleakClient = None
    BleakScanner = None

if TYPE_CHECKING:
    from .config import OBDConfig

log = logging.getLogger(__name__)


PID_DEFS = {
    "ENGINE_LOAD": ("0104", lambda b: b[0] * 100.0 / 255.0, 1),
    "COOLANT_TEMP": ("0105", lambda b: b[0] - 40.0, 1),
    "RPM": ("010C", lambda b: ((b[0] * 256) + b[1]) / 4.0, 2),
    "SPEED": ("010D", lambda b: float(b[0]), 1),
    "THROTTLE_POS": ("0111", lambda b: b[0] * 100.0 / 255.0, 1),
}

PROMPT = ">"


class BleElm327:
    def __init__(self, cfg: "OBDConfig"):
        self.cfg = cfg
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
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)

    def command(self, command: str, timeout: float = 5.0) -> str:
        return self._run(self._command(command, timeout))

    def _run(self, coro):
        future: Future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    async def _connect(self) -> None:
        if BleakClient is None or BleakScanner is None:
            raise RuntimeError("BLE transport requires the 'bleak' Python package")

        device = None
        if self.cfg.ble_address:
            device = await BleakScanner.find_device_by_address(
                self.cfg.ble_address, timeout=self.cfg.timeout
            )
        if device is None:
            device = await BleakScanner.find_device_by_filter(
                lambda d, _: bool(d.name and self.cfg.ble_name.lower() in d.name.lower()),
                timeout=self.cfg.timeout,
            )
        if device is None:
            raise RuntimeError("BLE OBD adapter not found")

        log.info("connecting to BLE OBD adapter %s (%s)", device.name, device.address)
        self.client = BleakClient(device)
        await self.client.connect()
        self.write_uuid, self.notify_uuid = self._select_characteristics()
        self.notify_event = asyncio.Event()
        await self.client.start_notify(self.notify_uuid, self._on_notify)

        for cmd in ["ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0"]:
            await self._command(cmd, timeout=8)

    async def _close(self) -> None:
        if self.client and self.client.is_connected:
            if self.notify_uuid:
                try:
                    await self.client.stop_notify(self.notify_uuid)
                except Exception:
                    pass
            await self.client.disconnect()

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

    async def _command(self, command: str, timeout: float = 5.0) -> str:
        if not self.client or not self.write_uuid or not self.notify_event:
            raise RuntimeError("BLE OBD adapter is not connected")
        self.buffer = ""
        self.notify_event.clear()
        await self.client.write_gatt_char(
            self.write_uuid, (command.strip() + "\r").encode(), response=False
        )
        try:
            await asyncio.wait_for(self.notify_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return _clean_response(self.buffer, command)


def _clean_response(raw: str, command: str) -> str:
    text = raw.replace("\r", "\n").replace(PROMPT, "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(line for line in lines if line.upper() != command.upper())


def parse_pid_response(response: str, mode_pid: str, needed: int) -> Optional[List[int]]:
    wanted = mode_pid.upper()
    payload = re.sub(r"[^0-9A-Fa-f]", "", response).upper()
    # 010C response starts with 410C, then data bytes.
    mode = int(wanted[:2], 16)
    marker = f"{mode + 0x40:02X}{wanted[2:]}"
    idx = payload.find(marker)
    if idx < 0:
        return None
    data = payload[idx + len(marker):]
    if len(data) < needed * 2:
        return None
    return [int(data[i:i + 2], 16) for i in range(0, needed * 2, 2)]


class BleOBDReader:
    def __init__(self, cfg: "OBDConfig"):
        self.cfg = cfg
        self.adapter = BleElm327(cfg)
        self.pids = [name for name in cfg.core_pids if name in PID_DEFS]

    def connect(self) -> None:
        self.adapter.connect()
        log.info("BLE OBD ready, %d core PIDs configured", len(self.pids))

    def read(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for name in self.pids:
            command, decoder, needed = PID_DEFS[name]
            response = self.adapter.command(command, timeout=self.cfg.timeout)
            data = parse_pid_response(response, command, needed)
            if data is None:
                continue
            out[name] = decoder(data)
            time.sleep(0.02)
        return out

    def field_names(self) -> List[str]:
        return self.pids

    def close(self) -> None:
        self.adapter.close()
