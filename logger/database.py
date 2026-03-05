from __future__ import annotations
import sqlite3
import os
from typing import List, Dict, Any, Optional
from logger.config import AppConfig

DB_PATH = os.path.join("data", "logger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS plcs (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ip   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id              INTEGER PRIMARY KEY,
    plc_id          INTEGER NOT NULL REFERENCES plcs(id),
    name            TEXT NOT NULL,
    register_type   TEXT NOT NULL,
    address         INTEGER NOT NULL,
    data_type       TEXT NOT NULL,
    unit            TEXT
);

CREATE TABLE IF NOT EXISTS log_data (
    id        INTEGER PRIMARY KEY,
    ts        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tag_id    INTEGER NOT NULL REFERENCES tags(id),
    value     REAL,
    quality   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_log_ts  ON log_data(ts);
CREATE INDEX IF NOT EXISTS idx_log_tag ON log_data(tag_id);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(config: AppConfig) -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_conn() as conn:
        conn.executescript(SCHEMA)
        for plc in config.plcs:
            row = conn.execute(
                "SELECT id FROM plcs WHERE name=? AND ip=?", (plc.name, plc.ip)
            ).fetchone()
            if row:
                plc_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO plcs (name, ip) VALUES (?, ?)", (plc.name, plc.ip)
                )
                plc_id = cur.lastrowid

            for tag in plc.tags:
                exists = conn.execute(
                    "SELECT id FROM tags WHERE plc_id=? AND name=?", (plc_id, tag.name)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO tags (plc_id, name, register_type, address, data_type, unit) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (plc_id, tag.name, tag.register_type, tag.address, tag.data_type, tag.unit),
                    )
        conn.commit()


def get_tag_id(plc_name: str, tag_name: str) -> Optional[int]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT t.id FROM tags t JOIN plcs p ON t.plc_id=p.id "
            "WHERE p.name=? AND t.name=?",
            (plc_name, tag_name),
        ).fetchone()
        return row["id"] if row else None


def insert_reading(tag_id: int, value: Optional[float], quality: int = 0) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO log_data (tag_id, value, quality) VALUES (?, ?, ?)",
            (tag_id, value, quality),
        )
        conn.commit()


def get_latest() -> List[Dict[str, Any]]:
    """Return the most recent reading for every tag, with PLC and tag metadata."""
    sql = """
    SELECT
        p.id   AS plc_id,
        p.name AS plc_name,
        p.ip   AS plc_ip,
        t.id   AS tag_id,
        t.name AS tag_name,
        t.unit,
        t.data_type,
        t.register_type,
        ld.value,
        ld.quality,
        ld.ts
    FROM tags t
    JOIN plcs p ON t.plc_id = p.id
    LEFT JOIN log_data ld ON ld.id = (
        SELECT id FROM log_data WHERE tag_id = t.id ORDER BY ts DESC LIMIT 1
    )
    ORDER BY p.id, t.id
    """
    with _get_conn() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


def get_history(tag_id: int, minutes: int = 60) -> List[Dict[str, Any]]:
    sql = """
    SELECT ts, value, quality
    FROM log_data
    WHERE tag_id = ?
      AND ts >= datetime('now', ? || ' minutes')
    ORDER BY ts ASC
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (tag_id, f"-{minutes}")).fetchall()
        return [dict(r) for r in rows]


def get_alarms() -> List[Dict[str, Any]]:
    """Return bool tags whose most recent reading is 1 (true / alarm active)."""
    sql = """
    SELECT
        p.name AS plc_name,
        t.id   AS tag_id,
        t.name AS tag_name,
        ld.value,
        ld.ts
    FROM tags t
    JOIN plcs p ON t.plc_id = p.id
    JOIN log_data ld ON ld.id = (
        SELECT id FROM log_data WHERE tag_id = t.id ORDER BY ts DESC LIMIT 1
    )
    WHERE t.data_type = 'bool'
      AND ld.value = 1
      AND ld.quality = 0
    ORDER BY ld.ts DESC
    """
    with _get_conn() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
