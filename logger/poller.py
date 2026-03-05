from __future__ import annotations
import asyncio
import logging
import struct
from typing import Dict, Optional

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from logger.config import AppConfig, PLCConfig, TagConfig
from logger import database

log = logging.getLogger(__name__)

# Map Modbus 5-digit addresses to (register_type, 0-based offset)
# Productivity 1000 uses the classic 1-based Modbus address notation:
#   1xxxxx -> coils          (base 100001 -> offset address-100001, but config uses raw address)
#   3xxxxx -> input registers
#   4xxxxx -> holding registers
# The config stores the full Modbus address (e.g. 400001, 300001, 1).
# We strip the leading digit range to get the 0-based register offset.

def _resolve_address(tag: TagConfig) -> int:
    """Convert Modbus 5-digit address to 0-based register offset."""
    addr = tag.address
    if tag.register_type == "holding":
        return addr - 400001 if addr >= 400001 else addr
    elif tag.register_type == "input":
        return addr - 300001 if addr >= 300001 else addr
    elif tag.register_type in ("coil", "discrete"):
        return addr - 1 if addr >= 1 else addr
    return addr


def _decode_registers(registers: list, data_type: str) -> float:
    if data_type == "uint16":
        return float(registers[0])
    elif data_type == "int16":
        raw = registers[0]
        return float(raw if raw < 0x8000 else raw - 0x10000)
    elif data_type == "float32":
        # Big-endian: high word first
        packed = struct.pack(">HH", registers[0], registers[1])
        return struct.unpack(">f", packed)[0]
    elif data_type == "bool":
        return float(registers[0])
    return float(registers[0])


class PLCPoller:
    def __init__(self, plc: PLCConfig):
        self.plc = plc
        self._client: Optional[AsyncModbusTcpClient] = None
        self._tag_ids: Dict[str, int] = {}

    async def _ensure_connected(self) -> bool:
        if self._client is None:
            self._client = AsyncModbusTcpClient(
                host=self.plc.ip,
                port=self.plc.port,
                timeout=3,
            )
        if not self._client.connected:
            try:
                await self._client.connect()
            except Exception as exc:
                log.warning("Cannot connect to %s (%s): %s", self.plc.name, self.plc.ip, exc)
                return False
        return self._client.connected

    async def _read_tag(self, tag: TagConfig) -> tuple[Optional[float], int]:
        """Returns (value, quality). quality=0 good, 1=error."""
        offset = _resolve_address(tag)
        count = 2 if tag.data_type == "float32" else 1
        try:
            if tag.register_type == "holding":
                resp = await self._client.read_holding_registers(offset, count=count, slave=self.plc.unit_id)
            elif tag.register_type == "input":
                resp = await self._client.read_input_registers(offset, count=count, slave=self.plc.unit_id)
            elif tag.register_type == "coil":
                resp = await self._client.read_coils(offset, count=1, slave=self.plc.unit_id)
            elif tag.register_type == "discrete":
                resp = await self._client.read_discrete_inputs(offset, count=1, slave=self.plc.unit_id)
            else:
                return None, 1

            if resp.isError():
                log.warning("%s/%s Modbus error: %s", self.plc.name, tag.name, resp)
                return None, 1

            if tag.register_type in ("coil", "discrete"):
                value = float(resp.bits[0])
            else:
                value = _decode_registers(resp.registers, tag.data_type)

            return value, 0

        except (ModbusException, asyncio.TimeoutError, Exception) as exc:
            log.warning("%s/%s read error: %s", self.plc.name, tag.name, exc)
            return None, 1

    async def poll(self) -> None:
        connected = await self._ensure_connected()

        for tag in self.plc.tags:
            tag_id = self._tag_ids.get(tag.name)
            if tag_id is None:
                tag_id = database.get_tag_id(self.plc.name, tag.name)
                if tag_id is None:
                    log.error("No DB entry for %s/%s", self.plc.name, tag.name)
                    continue
                self._tag_ids[tag.name] = tag_id

            if not connected:
                database.insert_reading(tag_id, None, quality=1)
                continue

            value, quality = await self._read_tag(tag)
            database.insert_reading(tag_id, value, quality)

        log.debug("Polled %s (%d tags)", self.plc.name, len(self.plc.tags))

    async def close(self) -> None:
        if self._client and self._client.connected:
            self._client.close()


def build_scheduler(config: AppConfig) -> tuple[AsyncIOScheduler, list[PLCPoller]]:
    scheduler = AsyncIOScheduler()
    pollers: list[PLCPoller] = []

    for plc in config.plcs:
        poller = PLCPoller(plc)
        pollers.append(poller)
        scheduler.add_job(
            poller.poll,
            trigger="interval",
            seconds=config.poll_interval_seconds,
            id=f"poll_{plc.name}",
            max_instances=1,
            coalesce=True,
        )

    return scheduler, pollers
