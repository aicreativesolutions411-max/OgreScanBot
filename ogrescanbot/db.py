from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import aiosqlite

from .models import TokenScan


@dataclass(frozen=True)
class CallRecord:
    id: int
    chat_id: int
    token_address: str
    token_name: str
    token_symbol: str
    caller_user_id: int
    caller_name: str
    initial_cap: float
    peak_cap: float
    peak_multiple: float
    last_cap: float
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class TraderRecord:
    caller_user_id: int
    caller_name: str
    total_calls: int
    best_multiple: float
    avg_multiple: float
    hits: int


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                token_address TEXT NOT NULL,
                token_name TEXT NOT NULL,
                token_symbol TEXT NOT NULL,
                caller_user_id INTEGER NOT NULL,
                caller_name TEXT NOT NULL,
                initial_cap REAL NOT NULL,
                peak_cap REAL NOT NULL,
                peak_multiple REAL NOT NULL,
                last_cap REAL NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(chat_id, token_address)
            );
            CREATE INDEX IF NOT EXISTS idx_calls_chat_created ON calls(chat_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_calls_chat_peak ON calls(chat_id, peak_multiple DESC);
            """
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def upsert_call(
        self,
        chat_id: int,
        token: TokenScan,
        caller_user_id: int,
        caller_name: str,
    ) -> tuple[CallRecord, bool]:
        conn = self._conn()
        now = int(time.time())
        cap = token.cap_for_tracking
        if not cap or cap <= 0:
            raise ValueError("Token is missing market cap/FDV, cannot track call.")

        existing = await self.get_call(chat_id, token.address)
        if existing:
            peak_cap = max(existing.peak_cap, cap)
            peak_multiple = max(existing.peak_multiple, peak_cap / existing.initial_cap)
            await conn.execute(
                """
                UPDATE calls
                SET token_name = ?, token_symbol = ?, peak_cap = ?, peak_multiple = ?,
                    last_cap = ?, updated_at = ?
                WHERE id = ?
                """,
                (token.name, token.symbol, peak_cap, peak_multiple, cap, now, existing.id),
            )
            await conn.commit()
            return (await self.get_call(chat_id, token.address)) or existing, False

        await conn.execute(
            """
            INSERT INTO calls (
                chat_id, token_address, token_name, token_symbol, caller_user_id, caller_name,
                initial_cap, peak_cap, peak_multiple, last_cap, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                token.address,
                token.name,
                token.symbol,
                caller_user_id,
                caller_name,
                cap,
                cap,
                1.0,
                cap,
                now,
                now,
            ),
        )
        await conn.commit()
        record = await self.get_call(chat_id, token.address)
        if not record:
            raise RuntimeError("Inserted call could not be loaded.")
        return record, True

    async def get_call(self, chat_id: int, token_address: str) -> CallRecord | None:
        conn = self._conn()
        cursor = await conn.execute(
            "SELECT * FROM calls WHERE chat_id = ? AND token_address = ?",
            (chat_id, token_address),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _row_to_call(row) if row else None

    async def leaderboard(self, chat_id: int, since_ts: int | None = None, limit: int = 10) -> list[CallRecord]:
        conn = self._conn()
        if since_ts:
            cursor = await conn.execute(
                """
                SELECT * FROM calls
                WHERE chat_id = ? AND created_at >= ?
                ORDER BY peak_multiple DESC, peak_cap DESC
                LIMIT ?
                """,
                (chat_id, since_ts, limit),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT * FROM calls
                WHERE chat_id = ?
                ORDER BY peak_multiple DESC, peak_cap DESC
                LIMIT ?
                """,
                (chat_id, limit),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_row_to_call(row) for row in rows]

    async def top_traders(
        self,
        chat_id: int,
        since_ts: int | None = None,
        min_hit_multiple: float = 2.0,
        limit: int = 5,
    ) -> list[TraderRecord]:
        conn = self._conn()
        if since_ts:
            cursor = await conn.execute(
                """
                SELECT
                    caller_user_id,
                    caller_name,
                    COUNT(*) AS total_calls,
                    MAX(peak_multiple) AS best_multiple,
                    AVG(peak_multiple) AS avg_multiple,
                    SUM(CASE WHEN peak_multiple >= ? THEN 1 ELSE 0 END) AS hits
                FROM calls
                WHERE chat_id = ? AND created_at >= ?
                GROUP BY caller_user_id, caller_name
                ORDER BY best_multiple DESC, hits DESC, total_calls DESC
                LIMIT ?
                """,
                (min_hit_multiple, chat_id, since_ts, limit),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT
                    caller_user_id,
                    caller_name,
                    COUNT(*) AS total_calls,
                    MAX(peak_multiple) AS best_multiple,
                    AVG(peak_multiple) AS avg_multiple,
                    SUM(CASE WHEN peak_multiple >= ? THEN 1 ELSE 0 END) AS hits
                FROM calls
                WHERE chat_id = ?
                GROUP BY caller_user_id, caller_name
                ORDER BY best_multiple DESC, hits DESC, total_calls DESC
                LIMIT ?
                """,
                (min_hit_multiple, chat_id, limit),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_row_to_trader(row) for row in rows]

    async def stats(self, chat_id: int, since_ts: int | None, min_hit_multiple: float) -> dict[str, float | int]:
        conn = self._conn()
        params: tuple[int, ...] | tuple[int, int]
        if since_ts:
            cursor = await conn.execute(
                "SELECT peak_multiple FROM calls WHERE chat_id = ? AND created_at >= ?",
                (chat_id, since_ts),
            )
        else:
            cursor = await conn.execute("SELECT peak_multiple FROM calls WHERE chat_id = ?", (chat_id,))
        rows = await cursor.fetchall()
        await cursor.close()
        multiples = [float(row["peak_multiple"]) for row in rows]
        if not multiples:
            return {"calls": 0, "hit_rate": 0, "median": 0, "return": 0}
        hits = [value for value in multiples if value >= min_hit_multiple]
        return {
            "calls": len(multiples),
            "hit_rate": round((len(hits) / len(multiples)) * 100),
            "median": statistics.median(multiples),
            "return": max(multiples),
        }

    def _conn(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("Database is not open.")
        return self.conn


def period_to_since(period: str | None) -> tuple[str, int | None]:
    normalized = (period or "all").strip().lower()
    now = int(time.time())
    mapping = {
        "1d": 86400,
        "24h": 86400,
        "1w": 86400 * 7,
        "7d": 86400 * 7,
        "30d": 86400 * 30,
        "1m": 86400 * 30,
        "all": 0,
    }
    seconds = mapping.get(normalized, mapping["all"])
    label = normalized if normalized in mapping else "all"
    return label, now - seconds if seconds else None


def _row_to_call(row: aiosqlite.Row) -> CallRecord:
    return CallRecord(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        token_address=str(row["token_address"]),
        token_name=str(row["token_name"]),
        token_symbol=str(row["token_symbol"]),
        caller_user_id=int(row["caller_user_id"]),
        caller_name=str(row["caller_name"]),
        initial_cap=float(row["initial_cap"]),
        peak_cap=float(row["peak_cap"]),
        peak_multiple=float(row["peak_multiple"]),
        last_cap=float(row["last_cap"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


def _row_to_trader(row: aiosqlite.Row) -> TraderRecord:
    return TraderRecord(
        caller_user_id=int(row["caller_user_id"]),
        caller_name=str(row["caller_name"]),
        total_calls=int(row["total_calls"]),
        best_multiple=float(row["best_multiple"]),
        avg_multiple=float(row["avg_multiple"]),
        hits=int(row["hits"]),
    )
