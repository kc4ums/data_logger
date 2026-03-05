# Data Logger for MDF Molding Mill — Automation Direct Productivity 1000 PLCs

## Context

A mill producing MDF molding needs to collect production and machine health data from 6–15 Productivity 1000 PLCs simultaneously. The data logger will poll each PLC over Modbus TCP every 5–10 seconds, store results in a local SQLite database, and expose a browser-based web dashboard for live monitoring and historical trends.

---

## Project Structure

```
C:\Projects\data_logger\
├── config.yaml              # PLC list, register maps, poll interval
├── requirements.txt
├── main.py                  # Entry point: starts poller + web server
├── logger/
│   ├── __init__.py
│   ├── config.py            # Load/validate config.yaml (dataclasses)
│   ├── poller.py            # Async Modbus TCP polling engine
│   └── database.py          # SQLite schema creation + write/read helpers
└── web/
    ├── app.py               # Flask app: REST API + serve dashboard
    ├── templates/
    │   └── index.html       # Dashboard: live table + Chart.js trends
    └── static/
        └── app.js           # AJAX polling, chart rendering
```

Data directory `data/logger.db` is auto-created at first run.

---

## Dependencies (requirements.txt)

- `pymodbus>=3.6` — async Modbus TCP client
- `flask>=3.0` — web server + REST API
- `pyyaml` — config file parsing
- `apscheduler>=3.10` — per-PLC scheduled polling jobs

---

## Configuration (config.yaml)

```yaml
poll_interval_seconds: 5
web_port: 5000

plcs:
  - name: "Moulder Station 1"
    ip: "192.168.1.10"
    port: 502
    unit_id: 1
    tags:
      - name: "part_count"
        register_type: holding   # holding | input | coil | discrete
        address: 400001
        data_type: uint16        # uint16 | int16 | float32 | bool
        unit: "pcs"
      - name: "feed_speed"
        register_type: holding
        address: 400010
        data_type: float32
        unit: "m/min"
      - name: "spindle_load"
        register_type: input
        address: 300001
        data_type: uint16
        unit: "%"
      - name: "fault_active"
        register_type: coil
        address: 1
        data_type: bool
        unit: ""
```

Each PLC entry defines its IP, Modbus unit ID, and a list of named tags with register addresses, types, and engineering units.

---

## Database Schema (logger/database.py)

```sql
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
    quality   INTEGER NOT NULL DEFAULT 0  -- 0=good, 1=comm error
);

CREATE INDEX IF NOT EXISTS idx_log_ts ON log_data(ts);
CREATE INDEX IF NOT EXISTS idx_log_tag ON log_data(tag_id);
```

---

## Polling Engine (logger/poller.py)

- Uses `pymodbus.client.AsyncModbusTcpClient` (one client per PLC)
- `APScheduler AsyncIOScheduler` fires a job per PLC every `poll_interval_seconds`
- Each job:
  1. Connects (or reuses existing connection)
  2. Reads each tag's register (batches reads where addresses are contiguous)
  3. Decodes raw register value → engineering value (handles float32 two-register decode)
  4. Writes row to `log_data` via `database.py`; sets `quality=1` on Modbus exception
- Reconnect: on connection failure, log quality=1 for all tags, retry next cycle

---

## Web Layer (web/app.py)

Flask REST endpoints:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Serve dashboard HTML |
| GET | `/api/plcs` | List all PLCs with latest tag values |
| GET | `/api/tags/<tag_id>/history?minutes=60` | Return time-series for one tag |
| GET | `/api/alarms` | Tags with `data_type=bool` currently true |

Dashboard (`index.html` + `app.js`):
- Auto-refreshes live table every 5 seconds via AJAX to `/api/plcs`
- Clicking a tag opens a Chart.js line chart fetching from `/api/tags/<id>/history`
- Alarm tags highlighted in red when value = 1
- Shows PLC connection quality (green/red badge) based on most recent `quality` field

---

## Entry Point (main.py)

```python
# Starts APScheduler (asyncio) for polling
# Starts Flask in a background thread
# Graceful shutdown on SIGINT
```

---

## Implementation Steps

1. `requirements.txt` — pin all dependencies
2. `logger/config.py` — dataclasses + YAML loader with validation
3. `logger/database.py` — schema creation, `insert_reading()`, `get_latest()`, `get_history()`
4. `logger/poller.py` — async Modbus polling with APScheduler, register batch logic
5. `web/app.py` — Flask app + 4 REST routes using `database.py` read helpers
6. `web/templates/index.html` + `web/static/app.js` — responsive dashboard table + Chart.js
7. `main.py` — wire everything together, handle startup/shutdown
8. `config.yaml` — example config for 2 sample PLCs

---

## Verification

1. Install deps: `pip install -r requirements.txt`
2. Edit `config.yaml` with real PLC IPs (or use a Modbus simulator like `diagslave` or `ModRSsim2` for offline testing)
3. Run: `python main.py`
4. Open browser: `http://localhost:5000`
5. Confirm:
   - Dashboard shows all configured PLCs and their tags
   - Values update every 5 seconds
   - Clicking a tag shows a trend chart
   - Disconnecting a PLC causes its badge to turn red and quality flag = 1 in DB
   - `sqlite3 data/logger.db "SELECT * FROM log_data LIMIT 20;"` shows rows accumulating
