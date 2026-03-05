# Data Logger — How Everything Ties Together

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        config.yaml                              │
│  poll_interval, web_port, PLC list (IP, tags, addresses)        │
└───────────────────────────┬─────────────────────────────────────┘
                            │  read once at startup
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                 │
│  asyncio.run(async_main())                                      │
│    1. load_config()   → AppConfig dataclass                     │
│    2. init_db()       → creates SQLite tables + seeds rows      │
│    3. Flask thread    → daemon thread, runs web/app.py          │
│    4. build_scheduler() → APScheduler fires poll jobs           │
│    5. await stop_event  → blocks until Ctrl+C                   │
└────────────┬──────────────────────────────┬────────────────────┘
             │ asyncio event loop           │ background thread
             ▼                              ▼
┌────────────────────────┐      ┌───────────────────────────────┐
│    logger/poller.py    │      │        web/app.py             │
│                        │      │                               │
│  PLCPoller (per PLC)   │      │  Flask routes:                │
│  ┌──────────────────┐  │      │   GET /          → index.html │
│  │ AsyncModbusTCP   │  │      │   GET /api/plcs  → JSON       │
│  │  client          │  │      │   GET /api/tags/ → JSON       │
│  │  .connect()      │  │      │        history                │
│  │  .read_holding_  │  │      │   GET /api/alarms → JSON      │
│  │   registers()    │  │      │                               │
│  │  .read_coils()   │  │      │  Calls database.get_latest()  │
│  └────────┬─────────┘  │      │         database.get_history()│
│           │ raw bytes  │      │         database.get_alarms() │
│  _decode_registers()   │      └───────────────┬───────────────┘
│  → float value         │                      │
│           │            │                      │
│  database.insert_      │                      │
│    reading(tag_id,     │                      │
│      value, quality)   │                      │
└────────────┬───────────┘                      │
             │ writes                           │ reads
             ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    logger/database.py                           │
│                    data/logger.db  (SQLite)                     │
│                                                                 │
│  ┌──────────┐    ┌──────────────────────┐    ┌──────────────┐  │
│  │  plcs    │    │        tags          │    │  log_data    │  │
│  │──────────│    │──────────────────────│    │──────────────│  │
│  │ id  (PK) │◄───│ plc_id  (FK)         │◄───│ tag_id  (FK) │  │
│  │ name     │    │ id  (PK)             │    │ id  (PK)     │  │
│  │ ip       │    │ name                 │    │ ts  (time)   │  │
│  └──────────┘    │ register_type        │    │ value (REAL) │  │
│                  │ address              │    │ quality 0/1  │  │
│                  │ data_type            │    └──────────────┘  │
│                  │ unit                 │                       │
│                  └──────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP GET /api/plcs (JSON)
                              │ every 5 seconds via AJAX
┌─────────────────────────────────────────────────────────────────┐
│                     Browser Dashboard                           │
│              web/templates/index.html                           │
│              web/static/app.js                                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Live Table (auto-refresh 5s)                            │  │
│  │  PLC Name | Tag Name | Value | Unit | Quality            │  │
│  │  Moulder 1 | part_count | 142 | pcs | ● green           │  │
│  │  Moulder 1 | fault_active | 0 | — | ● green             │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Chart.js Trend (click any tag)                          │  │
│  │  /api/tags/<id>/history?minutes=60 → time-series JSON    │  │
│  │  ▁▂▄▆▇█▇▆▄▂▁ (line chart)                               │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — Step by Step

### Startup Sequence

```
python main.py
     │
     ├─ 1. load_config("config.yaml")
     │       Reads YAML → builds AppConfig / PLCConfig / TagConfig dataclasses
     │       Validates: IP not empty, port 1-65535, register_type in allowed set
     │
     ├─ 2. init_db(config)
     │       Creates data/logger.db if missing
     │       Runs CREATE TABLE IF NOT EXISTS for plcs, tags, log_data
     │       Inserts a row in plcs + tags for each entry in config.yaml
     │       (idempotent — safe to run multiple times)
     │
     ├─ 3. Flask thread starts  (daemon=True → dies when main exits)
     │       Binds to 0.0.0.0:5000
     │
     └─ 4. APScheduler starts
             Creates one PLCPoller per PLC
             Schedules poller.poll() every N seconds per PLC
```

### Every Poll Cycle (e.g. every 5 seconds, per PLC)

```
APScheduler fires → PLCPoller.poll()
     │
     ├─ _ensure_connected()
     │    AsyncModbusTcpClient.connect() to PLC IP:502
     │    If fail → quality=1 for all tags, skip reads
     │
     └─ For each tag in this PLC:
          │
          ├─ Look up tag_id from DB (cached in memory after first poll)
          │
          ├─ _read_tag(tag)
          │    _resolve_address() → converts 400001 → register offset 0
          │    read_holding_registers() / read_input_registers() /
          │      read_coils() / read_discrete_inputs()
          │    _decode_registers() → uint16, int16, float32, or bool → float
          │
          └─ database.insert_reading(tag_id, value, quality)
               INSERT INTO log_data (tag_id, value, quality) VALUES (?, ?, ?)
```

### Browser Request — Live Table

```
Browser (every 5s) → GET /api/plcs
     │
     └─ web/app.py: api_plcs()
          database.get_latest()
               SELECT latest log_data row per tag using correlated subquery
               JOINs plcs + tags for metadata
          Groups rows by PLC → returns JSON array
     │
     └─ Browser renders table, colors quality badge green/red
```

### Browser Request — Trend Chart

```
User clicks tag → GET /api/tags/7/history?minutes=60
     │
     └─ web/app.py: api_tag_history(tag_id=7)
          database.get_history(7, 60)
               SELECT ts, value, quality FROM log_data
               WHERE tag_id=7 AND ts >= now - 60 minutes
          Returns JSON array [{ts, value, quality}, ...]
     │
     └─ app.js feeds array into Chart.js → line chart renders
```

---

## File Roles — Quick Reference

| File | Language / Tool | Role |
|---|---|---|
| `config.yaml` | YAML | Single source of truth for PLCs, tags, poll rate |
| `logger/config.py` | Python dataclasses + PyYAML | Loads + validates config into typed objects |
| `logger/database.py` | Python + sqlite3 | All DB reads/writes — schema, insert, query |
| `logger/poller.py` | Python asyncio + pymodbus + APScheduler | Reads PLCs over Modbus TCP, writes to DB |
| `web/app.py` | Flask | REST API — reads DB, returns JSON to browser |
| `web/templates/index.html` | HTML | Dashboard page shell |
| `web/static/app.js` | JavaScript | AJAX polling + Chart.js rendering |
| `main.py` | Python | Wires everything together, manages threads |
| `data/logger.db` | SQLite file | All time-series readings (auto-created) |

---

## Key Concepts Explained

### Why Two Threads?

- **asyncio event loop** — Modbus TCP uses `async/await`. You can't block waiting for one PLC while others need polling. Asyncio lets all PLCs poll "at the same time" without multiple OS threads.
- **Flask background thread** — Flask's built-in server is synchronous. It runs in its own thread so it doesn't block the asyncio loop. They share the SQLite database safely because SQLite's WAL mode allows one writer + many readers simultaneously.

### Why SQLite?

- Zero-config, file-based, no server to install.
- `WAL` (Write-Ahead Log) mode lets the poller write rows while Flask reads them without locking each other out.
- `check_same_thread=False` allows both the asyncio thread and the Flask thread to open connections.

### Why APScheduler?

- You need one independent repeating job per PLC. APScheduler's `AsyncIOScheduler` integrates with asyncio — each job runs as a coroutine on the existing event loop, so 15 PLCs polling simultaneously works cleanly.

### How Does a Register Value Get to the Browser?

```
PLC memory register (raw 16-bit integer)
  → Modbus TCP network packet
    → pymodbus resp.registers[0]
      → _decode_registers() → Python float
        → database.insert_reading() → SQLite row
          → database.get_latest() → Python dict
            → Flask jsonify() → HTTP JSON response
              → JavaScript fetch() → Chart.js or table cell
```

---

## Database Schema

```sql
-- One row per PLC defined in config.yaml
CREATE TABLE plcs (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ip   TEXT NOT NULL
);

-- One row per tag per PLC
CREATE TABLE tags (
    id            INTEGER PRIMARY KEY,
    plc_id        INTEGER NOT NULL REFERENCES plcs(id),
    name          TEXT NOT NULL,
    register_type TEXT NOT NULL,   -- holding | input | coil | discrete
    address       INTEGER NOT NULL,
    data_type     TEXT NOT NULL,   -- uint16 | int16 | float32 | bool
    unit          TEXT
);

-- One row written every poll cycle per tag
CREATE TABLE log_data (
    id      INTEGER PRIMARY KEY,
    ts      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tag_id  INTEGER NOT NULL REFERENCES tags(id),
    value   REAL,
    quality INTEGER NOT NULL DEFAULT 0  -- 0=good, 1=comm error
);
```

**Relationships:**
```
plcs (1) ──── (many) tags (1) ──── (many) log_data
```

---

## REST API Reference

| Method | Route | Returns |
|---|---|---|
| `GET` | `/` | Dashboard HTML page |
| `GET` | `/api/plcs` | All PLCs with their latest tag values |
| `GET` | `/api/tags/<id>/history?minutes=60` | Time-series for one tag |
| `GET` | `/api/alarms` | Bool tags currently reading `1` (fault active) |

### Example `/api/plcs` Response

```json
[
  {
    "id": 1,
    "name": "Moulder Station 1",
    "ip": "192.168.1.10",
    "tags": [
      {
        "id": 1,
        "name": "part_count",
        "unit": "pcs",
        "data_type": "uint16",
        "value": 142.0,
        "quality": 0,
        "ts": "2026-03-05 08:30:00"
      }
    ]
  }
]
```

---

## Running the Application

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit config.yaml with your PLC IPs
#    (or use a Modbus simulator like ModRSsim2 for offline testing)

# 3. Start the application
python main.py

# 4. Open the dashboard
#    http://localhost:5000

# 5. Inspect the database directly (optional)
sqlite3 data/logger.db "SELECT * FROM log_data ORDER BY ts DESC LIMIT 20;"
```

---

## Modbus Address Reference

The Productivity 1000 uses classic 5-digit Modbus notation. The poller strips the leading range digit to get the 0-based register offset sent over the wire.

| Config Address | Register Type | 0-based Offset Sent |
|---|---|---|
| `400001` | holding | `0` |
| `400010` | holding | `9` |
| `300001` | input | `0` |
| `1` | coil | `0` |

### Data Type Decoding

| `data_type` | Registers Read | Decode Method |
|---|---|---|
| `uint16` | 1 | `registers[0]` as-is |
| `int16` | 1 | Two's complement if `>= 0x8000` |
| `float32` | 2 | Big-endian `struct.unpack(">f", ...)` |
| `bool` | 1 | `bits[0]` from coil/discrete read |
