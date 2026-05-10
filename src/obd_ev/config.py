import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import yaml


@dataclass
class OBDConfig:
    ble_address: Optional[str] = None
    ble_name: str = "VEEPEAK"
    ble_write_uuid: Optional[str] = None
    ble_notify_uuid: Optional[str] = None
    timeout: int = 30
    reconnect_seconds: int = 15
    core_pids: List[str] = field(default_factory=lambda: [
        "RPM", "SPEED", "THROTTLE_POS", "COOLANT_TEMP", "ENGINE_LOAD",
    ])


@dataclass
class GPSConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 2947


@dataclass
class IMUConfig:
    enabled: bool = True
    i2c_address: int = 0x68
    sample_hz: int = 100
    lowpass_alpha: float = 0.1


@dataclass
class LoggerConfig:
    output_dir: str = "./logs"
    rotate_each_run: bool = True
    flush_every: int = 10
    uploaded_subdir: str = "uploaded"


@dataclass
class DeviceConfig:
    id: Optional[str] = None


@dataclass
class Config:
    obd: OBDConfig = field(default_factory=OBDConfig)
    gps: GPSConfig = field(default_factory=GPSConfig)
    imu: IMUConfig = field(default_factory=IMUConfig)
    logger: LoggerConfig = field(default_factory=LoggerConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)


def load(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    raw = {}
    if p.exists():
        with p.open() as f:
            raw = yaml.safe_load(f) or {}

    cfg = Config(
        obd=OBDConfig(**(raw.get("obd") or {})),
        gps=GPSConfig(**(raw.get("gps") or {})),
        imu=IMUConfig(**(raw.get("imu") or {})),
        logger=LoggerConfig(**(raw.get("logger") or {})),
        device=DeviceConfig(**(raw.get("device") or {})),
    )

    # Per-device override: env > config > hostname.
    if not cfg.device.id:
        cfg.device.id = os.environ.get("OBD_EV_DEVICE_ID") or socket.gethostname()
    return cfg
