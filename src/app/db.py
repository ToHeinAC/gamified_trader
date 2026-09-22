"""SQLite persistence for users, settings, resets and rounds (PRD M5, M6)."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from app.settings_rules import (
    FEE_DEFAULT_TENTHS,
    INTEREST_DEFAULT_TENTHS,
    LEV_MID_DEFAULT,
    LEV_PRO_DEFAULT,
    UserSettings,
    name_key,
)

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  start_capital_cents INTEGER NOT NULL CHECK (start_capital_cents BETWEEN 100000 AND 100000000),
  balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
  lev_mid INTEGER NOT NULL CHECK (lev_mid BETWEEN 2 AND 20),
  lev_pro INTEGER NOT NULL CHECK (lev_pro BETWEEN 2 AND 20 AND lev_mid <= lev_pro),
  interest_tenths INTEGER NOT NULL CHECK (interest_tenths BETWEEN 0 AND 200),
  fee_tenths INTEGER NOT NULL CHECK (fee_tenths BETWEEN 0 AND 100),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resets (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  at TEXT NOT NULL,
  balance_before_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  snapshot_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  t0 TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'done')),
  level TEXT, leverage INTEGER, fee_tenths INTEGER, interest_tenths INTEGER,
  option TEXT, v REAL, pnl_cents INTEGER, fee_cents INTEGER, financing_cents INTEGER,
  points INTEGER, balance_before_cents INTEGER, balance_after_cents INTEGER,
  created_at TEXT NOT NULL, confirmed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_round ON rounds(user_id) WHERE status = 'open';
"""

_UPSERT_ACTIVE_USER = (
    "INSERT INTO app_state (key, value) VALUES ('active_user_id', ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)


@dataclass(frozen=True)
class UserRow:
    id: int
    name: str
    start_capital_cents: int
    balance_cents: int
    lev_mid: int
    lev_pro: int
    interest_tenths: int
    fee_tenths: int


def _row_to_user(row: sqlite3.Row) -> UserRow:
    return UserRow(
        id=row["id"],
        name=row["name"],
        start_capital_cents=row["start_capital_cents"],
        balance_cents=row["balance_cents"],
        lev_mid=row["lev_mid"],
        lev_pro=row["lev_pro"],
        interest_tenths=row["interest_tenths"],
        fee_tenths=row["fee_tenths"],
    )


@dataclass(frozen=True)
class RoundRow:
    id: int
    user_id: int
    snapshot_id: str
    ticker: str
    t0: date
    status: str
    level: str | None
    leverage: int | None
    fee_tenths: int | None
    interest_tenths: int | None
    option: str | None
    v: float | None
    pnl_cents: int | None
    fee_cents: int | None
    financing_cents: int | None
    points: int | None
    balance_before_cents: int | None
    balance_after_cents: int | None
    created_at: str
    confirmed_at: str | None


@dataclass(frozen=True)
class Stats:
    rounds: int
    points_total: int
    points_avg: float
    optimal_share: float
    balance_cents: int
    start_capital_cents: int
    resets: int


class RoundOutcome(Protocol):
    """Structural match for game.RoundOutcome, without importing it (avoids a db<->game cycle).

    Declared as read-only properties: game.RoundOutcome is a frozen dataclass, and a plain
    attribute here would require a writable counterpart, which frozen fields aren't.
    """

    @property
    def level(self) -> str: ...
    @property
    def leverage(self) -> int: ...
    @property
    def fee_tenths(self) -> int: ...
    @property
    def interest_tenths(self) -> int: ...
    @property
    def option(self) -> str: ...
    @property
    def v(self) -> float: ...
    @property
    def pnl_cents(self) -> int: ...
    @property
    def fee_cents(self) -> int: ...
    @property
    def financing_cents(self) -> int: ...
    @property
    def points(self) -> int: ...
    @property
    def balance_after_cents(self) -> int: ...


class _ConfirmRolledBack(Exception):
    pass


def _row_to_round(row: sqlite3.Row) -> RoundRow:
    return RoundRow(
        id=row["id"],
        user_id=row["user_id"],
        snapshot_id=row["snapshot_id"],
        ticker=row["ticker"],
        t0=date.fromisoformat(row["t0"]),
        status=row["status"],
        level=row["level"],
        leverage=row["leverage"],
        fee_tenths=row["fee_tenths"],
        interest_tenths=row["interest_tenths"],
        option=row["option"],
        v=row["v"],
        pnl_cents=row["pnl_cents"],
        fee_cents=row["fee_cents"],
        financing_cents=row["financing_cents"],
        points=row["points"],
        balance_before_cents=row["balance_before_cents"],
        balance_after_cents=row["balance_after_cents"],
        created_at=row["created_at"],
        confirmed_at=row["confirmed_at"],
    )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def create_user(self, name: str, start_capital_eur: int, now: str) -> int:
        cents = start_capital_eur * 100
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO users (name, name_key, start_capital_cents, balance_cents, "
                "lev_mid, lev_pro, interest_tenths, fee_tenths, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    name_key(name),
                    cents,
                    cents,
                    LEV_MID_DEFAULT,
                    LEV_PRO_DEFAULT,
                    INTEREST_DEFAULT_TENTHS,
                    FEE_DEFAULT_TENTHS,
                    now,
                ),
            )
            assert cur.lastrowid is not None
            user_id = cur.lastrowid
            conn.execute(_UPSERT_ACTIVE_USER, (str(user_id),))
        return user_id

    def users(self) -> list[UserRow]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY name_key").fetchall()
        return [_row_to_user(row) for row in rows]

    def user(self, user_id: int) -> UserRow | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row is not None else None

    def update_settings(self, user_id: int, s: UserSettings) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET start_capital_cents = ?, lev_mid = ?, lev_pro = ?, "
                "interest_tenths = ?, fee_tenths = ? WHERE id = ?",
                (
                    s.start_capital_eur * 100,
                    s.lev_mid,
                    s.lev_pro,
                    s.interest_tenths,
                    s.fee_tenths,
                    user_id,
                ),
            )

    def reset_balance(self, user_id: int, now: str) -> None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT balance_cents, start_capital_cents FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            before, start_capital = row["balance_cents"], row["start_capital_cents"]
            conn.execute(
                "UPDATE users SET balance_cents = ? WHERE id = ?", (start_capital, user_id)
            )
            conn.execute(
                "INSERT INTO resets (user_id, at, balance_before_cents) VALUES (?, ?, ?)",
                (user_id, now, before),
            )

    def reset_count(self, user_id: int) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM resets WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row[0])

    def active_user_id(self) -> int | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = 'active_user_id'"
            ).fetchone()
        return int(row["value"]) if row is not None else None

    def set_active_user(self, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(_UPSERT_ACTIVE_USER, (str(user_id),))

    def open_round(self, user_id: int) -> RoundRow | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM rounds WHERE user_id = ? AND status = 'open'", (user_id,)
            ).fetchone()
        return _row_to_round(row) if row is not None else None

    def last_round(self, user_id: int) -> RoundRow | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM rounds WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
            ).fetchone()
        return _row_to_round(row) if row is not None else None

    def insert_open_round(
        self, user_id: int, snapshot_id: str, ticker: str, t0: date, now: str
    ) -> RoundRow:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO rounds (user_id, snapshot_id, ticker, t0, status, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?)",
                (user_id, snapshot_id, ticker, t0.isoformat(), now),
            )
            assert cur.lastrowid is not None
            round_id = cur.lastrowid
        return RoundRow(
            id=round_id,
            user_id=user_id,
            snapshot_id=snapshot_id,
            ticker=ticker,
            t0=t0,
            status="open",
            level=None,
            leverage=None,
            fee_tenths=None,
            interest_tenths=None,
            option=None,
            v=None,
            pnl_cents=None,
            fee_cents=None,
            financing_cents=None,
            points=None,
            balance_before_cents=None,
            balance_after_cents=None,
            created_at=now,
            confirmed_at=None,
        )

    def play_counts(self, user_id: int) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT snapshot_id, COUNT(*) AS n FROM rounds WHERE user_id = ? "
                "GROUP BY snapshot_id",
                (user_id,),
            ).fetchall()
        return {row["snapshot_id"]: row["n"] for row in rows}

    def confirm_round(
        self, round_id: int, user_id: int, outcome: Callable[[int], RoundOutcome], now: str
    ) -> bool:
        try:
            with closing(self._connect()) as conn, conn:
                self._confirm_round_tx(conn, round_id, user_id, outcome, now)
        except _ConfirmRolledBack:
            return False
        return True

    def _confirm_round_tx(
        self,
        conn: sqlite3.Connection,
        round_id: int,
        user_id: int,
        outcome: Callable[[int], RoundOutcome],
        now: str,
    ) -> None:
        round_row = conn.execute(
            "SELECT status FROM rounds WHERE id = ? AND user_id = ?", (round_id, user_id)
        ).fetchone()
        if round_row is None or round_row["status"] != "open":
            raise _ConfirmRolledBack
        before = conn.execute(
            "SELECT balance_cents FROM users WHERE id = ?", (user_id,)
        ).fetchone()["balance_cents"]
        o = outcome(before)
        cur = conn.execute(
            "UPDATE rounds SET status = 'done', level = ?, leverage = ?, fee_tenths = ?, "
            "interest_tenths = ?, option = ?, v = ?, pnl_cents = ?, fee_cents = ?, "
            "financing_cents = ?, points = ?, balance_before_cents = ?, balance_after_cents = ?, "
            "confirmed_at = ? WHERE id = ? AND status = 'open'",
            (
                o.level,
                o.leverage,
                o.fee_tenths,
                o.interest_tenths,
                o.option,
                o.v,
                o.pnl_cents,
                o.fee_cents,
                o.financing_cents,
                o.points,
                before,
                o.balance_after_cents,
                now,
                round_id,
            ),
        )
        if cur.rowcount != 1:
            raise _ConfirmRolledBack
        conn.execute(
            "UPDATE users SET balance_cents = ? WHERE id = ?", (o.balance_after_cents, user_id)
        )

    def stats(self, user_id: int) -> Stats:
        with closing(self._connect()) as conn:
            user_row = conn.execute(
                "SELECT balance_cents, start_capital_cents FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            agg = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(points), 0) AS total, "
                "COALESCE(SUM(CASE WHEN points = 100 THEN 1 ELSE 0 END), 0) AS optimal "
                "FROM rounds WHERE user_id = ? AND status = 'done'",
                (user_id,),
            ).fetchone()
            resets = conn.execute(
                "SELECT COUNT(*) FROM resets WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        n = agg["n"]
        return Stats(
            rounds=n,
            points_total=agg["total"],
            points_avg=(agg["total"] / n) if n else 0.0,
            optimal_share=(agg["optimal"] / n) if n else 0.0,
            balance_cents=user_row["balance_cents"],
            start_capital_cents=user_row["start_capital_cents"],
            resets=resets,
        )
