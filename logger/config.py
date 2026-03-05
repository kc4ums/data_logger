from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import yaml


@dataclass
class TagConfig:
    name: str
    register_type: str          # holding | input | coil | discrete
    address: int
    data_type: str              # uint16 | int16 | float32 | bool
    unit: str = ""

    def __post_init__(self):
        valid_reg_types = {"holding", "input", "coil", "discrete"}
        valid_data_types = {"uint16", "int16", "float32", "bool"}
        if self.register_type not in valid_reg_types:
            raise ValueError(f"register_type '{self.register_type}' must be one of {valid_reg_types}")
        if self.data_type not in valid_data_types:
            raise ValueError(f"data_type '{self.data_type}' must be one of {valid_data_types}")
        if self.address < 0:
            raise ValueError(f"address must be >= 0, got {self.address}")


@dataclass
class PLCConfig:
    name: str
    ip: str
    port: int = 502
    unit_id: int = 1
    tags: List[TagConfig] = field(default_factory=list)

    def __post_init__(self):
        if not self.ip:
            raise ValueError(f"PLC '{self.name}' has no IP address")
        if not (1 <= self.port <= 65535):
            raise ValueError(f"PLC '{self.name}' port {self.port} out of range")
        if not (0 <= self.unit_id <= 247):
            raise ValueError(f"PLC '{self.name}' unit_id {self.unit_id} out of range")


@dataclass
class AppConfig:
    poll_interval_seconds: int
    web_port: int
    plcs: List[PLCConfig]


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    plcs = []
    for plc_raw in raw.get("plcs", []):
        tags = [TagConfig(**t) for t in plc_raw.get("tags", [])]
        plc_data = {k: v for k, v in plc_raw.items() if k != "tags"}
        plcs.append(PLCConfig(**plc_data, tags=tags))

    return AppConfig(
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 5)),
        web_port=int(raw.get("web_port", 5000)),
        plcs=plcs,
    )
