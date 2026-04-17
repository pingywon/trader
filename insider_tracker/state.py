"""Local SQLite store: dedupe filings we've already seen and keep a trade log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_filings (
    accession    TEXT PRIMARY KEY,
    symbol       TEXT,
    tx_code      TEXT,
    action       TEXT,
    reason       TEXT,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    accession       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    notional        REAL NOT NULL,
    insider_dollars REAL,
    insider_name    TEXT,
    insider_role    TEXT,
    alpaca_order_id TEXT,
    status          TEXT,
    submitted_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol    ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_submitted ON trades(submitted_at);
"""


class State:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_processed(self, accession: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM processed_filings WHERE accession = ?", (accession,)
            ).fetchone()
            return row is not None

    def mark_processed(
        self, accession: str, symbol: str, tx_code: str, action: str, reason: str
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO processed_filings"
                "(accession,symbol,tx_code,action,reason,processed_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    accession,
                    symbol,
                    tx_code,
                    action,
                    reason,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def record_trade(
        self,
        *,
        accession: str,
        symbol: str,
        notional: float,
        insider_dollars: float,
        insider_name: str,
        insider_role: str,
        alpaca_order_id: str | None,
        status: str,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO trades"
                "(accession,symbol,notional,insider_dollars,insider_name,insider_role,"
                " alpaca_order_id,status,submitted_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    accession,
                    symbol,
                    notional,
                    insider_dollars,
                    insider_name,
                    insider_role,
                    alpaca_order_id,
                    status,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def recent_processed(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM processed_filings ORDER BY processed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]

    def recent_trades(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM trades ORDER BY submitted_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
