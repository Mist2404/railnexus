"""SQLite 数据库操作"""

import json
import sqlite3
from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    telecode   TEXT NOT NULL UNIQUE,
    pinyin     TEXT,
    abbr       TEXT,
    city       TEXT
);

CREATE TABLE IF NOT EXISTS trains (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no        TEXT NOT NULL,
    train_number    TEXT NOT NULL,
    train_type      TEXT,
    from_telecode   TEXT,
    to_telecode     TEXT,
    from_station    TEXT,
    to_station      TEXT,
    depart_time     TEXT,
    arrive_time     TEXT,
    duration        TEXT,
    UNIQUE(train_no)
);

CREATE TABLE IF NOT EXISTS train_stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    train_no        TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    station_name    TEXT,
    station_telecode TEXT,
    arrive_time     TEXT,
    depart_time     TEXT,
    stop_minutes    TEXT,
    distance_km     TEXT,
    day_offset      INTEGER DEFAULT 0,
    UNIQUE(train_no, seq)
);

CREATE TABLE IF NOT EXISTS crawl_progress (
    phase    TEXT PRIMARY KEY,
    payload  TEXT
);

CREATE INDEX IF NOT EXISTS idx_stations_telecode ON stations(telecode);
CREATE INDEX IF NOT EXISTS idx_stations_city     ON stations(city);
CREATE INDEX IF NOT EXISTS idx_trains_train_no   ON trains(train_no);
CREATE INDEX IF NOT EXISTS idx_stops_train_no    ON train_stops(train_no);
CREATE INDEX IF NOT EXISTS idx_stops_station     ON train_stops(station_telecode);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def save_progress(phase: str, payload: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO crawl_progress VALUES (?, ?)",
        (phase, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def load_progress(phase: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT payload FROM crawl_progress WHERE phase = ?", (phase,)
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None
