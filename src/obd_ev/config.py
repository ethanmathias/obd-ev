from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import yaml


@dataclass
class OBDConfig:
    port: Optional[str] = None
    baudrate: int = 38400
    fast: bool = False
    timeout: int = 30
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


@dataclass
class Config:
    obd: OBDConfig = field(default_factory=OBDConfig)
    gps: GPSConfig = field(default_factory=GPSConfig)
    imu: IMUConfig = field(default_factory=IMUConfig)
    logger: LoggerConfig = field(default_factory=LoggerConfig)


def load(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        return Config()
    with p.open() as f:
        raw = yaml.safe_load(f) or {}
    return Config(
        obd=OBDConfig(**(raw.get("obd") or {})),
        gps=GPSConfig(**(raw.get("gps") or {})),
        imu=IMUConfig(**(raw.get("imu") or {})),
        logger=LoggerConfig(**(raw.get("logger") or {})),
    )
