"""24-hour rolling bandwidth history, persisted to SQLite.

Why SQLite (vs. JSON / pickle / flat file):
  - Built-in to Python, zero extra deps.
  - Cheap range-queries for the chart ("give me all rows from
    timestamp T to T+24h"), which a JSON-rolling-buffer would have
    to slurp into memory and filter.
  - Atomic writes per INSERT — if KaproTUN crashes mid-write, the
    db isn't half-corrupted like a partial JSON file would be.

Schema is intentionally trivial:
  - ts          INTEGER  Unix seconds, primary key. One row per
                         sample (about 1/min while connected).
  - up_bytes    INTEGER  Bytes sent during this minute's window.
  - down_bytes  INTEGER  Bytes received during this minute's window.

These are DELTA bytes (this minute only), not cumulative — easier
for the chart to plot as rate (just / 60 for B/s), and cleanup of
old rows doesn't lose accumulated totals.

Storage: one file at paths.data_dir() / 'bandwidth_history.db'.
~50 KB after 24h of continuous connection. Rolling cleanup keeps
it at that size — every record() call deletes anything older than
24h.

What's NOT recorded:
  - per-domain breakdown (would need DPI, conflicts with privacy)
  - per-app breakdown (needs WFP, separate large feature)
  - times when KaproTUN was running but disconnected
  - times when KaproTUN was closed (no measurement possible)
The chart honestly shows "tunnel traffic during minutes when we
were actively measuring". Empty stretches = was disconnected
or app was closed — that's accurate, not a bug.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from . import paths


_RETENTION_SECONDS = 24 * 60 * 60  # 24 hours rolling window


def _db_path() -> str:
    return str(paths.app_data_dir() / "bandwidth_history.db")


def _connect() -> sqlite3.Connection:
    """Open the db, ensuring schema exists. Cheap idempotent — sqlite
    only creates if not present. We don't keep a long-lived connection
    because sqlite3 modules aren't thread-safe by default, and the
    record/query call sites live in different Qt threads."""
    conn = sqlite3.connect(_db_path(), timeout=2.0)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bandwidth (
            ts          INTEGER PRIMARY KEY,
            up_bytes    INTEGER NOT NULL,
            down_bytes  INTEGER NOT NULL
        )
    """)
    return conn


@dataclass(frozen=True)
class Sample:
    ts: int          # unix seconds (start of the minute)
    up_bytes: int    # bytes sent during the minute
    down_bytes: int  # bytes received during the minute


def record(up_delta: int, down_delta: int, ts: Optional[int] = None) -> None:
    """Append one row. up_delta / down_delta are bytes counted during
    this sample window (≈ 60 seconds — the caller schedules us).

    Skips zero-sample rows to keep the db slim (idle minutes don't
    need a record — empty stretches in the chart correctly imply
    "nothing happened"). Negative deltas (xray restarted, counters
    rolled back) are clamped to 0 — they'd otherwise pollute the
    chart with phantom dips.
    """
    up_delta = max(0, int(up_delta))
    down_delta = max(0, int(down_delta))
    if up_delta == 0 and down_delta == 0:
        return
    if ts is None:
        ts = int(time.time())
    try:
        with _connect() as conn:
            # REPLACE so re-running the same minute doesn't duplicate.
            conn.execute(
                "INSERT OR REPLACE INTO bandwidth (ts, up_bytes, down_bytes) "
                "VALUES (?, ?, ?)",
                (ts, up_delta, down_delta),
            )
            # Rolling-window cleanup. Cheap (indexed by ts) so we do it
            # on every write rather than scheduling a separate cron-style
            # task.
            cutoff = ts - _RETENTION_SECONDS
            conn.execute("DELETE FROM bandwidth WHERE ts < ?", (cutoff,))
    except sqlite3.Error:
        # Stats are nice-to-have; never let a db hiccup propagate up
        # to break the main connect flow. Silent drop is acceptable.
        pass


def recent_24h() -> list[Sample]:
    """All rows from the last 24h, oldest first. Empty list on any
    sqlite error — same charity policy as record().
    """
    cutoff = int(time.time()) - _RETENTION_SECONDS
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT ts, up_bytes, down_bytes FROM bandwidth "
                "WHERE ts >= ? ORDER BY ts ASC",
                (cutoff,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [Sample(ts=r[0], up_bytes=r[1], down_bytes=r[2]) for r in rows]


def totals_24h() -> tuple[int, int]:
    """Sum of up_bytes / down_bytes over the last 24h. (0, 0) if no
    samples / db error.
    """
    cutoff = int(time.time()) - _RETENTION_SECONDS
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(up_bytes), 0), COALESCE(SUM(down_bytes), 0) "
                "FROM bandwidth WHERE ts >= ?",
                (cutoff,),
            ).fetchone()
    except sqlite3.Error:
        return (0, 0)
    return (int(row[0] or 0), int(row[1] or 0))


def clear() -> None:
    """Wipe all history. Used by the Settings UI "Очистить историю"
    button so a user who shared their screen / sold the laptop can
    quickly purge usage data without hunting the db file.
    """
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM bandwidth")
    except sqlite3.Error:
        pass
