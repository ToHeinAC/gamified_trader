"""SQLite persistence for users, settings and resets (PRD M5)."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from app.settings_rules import (
    FEE_DEFAULT_TENTHS,
    INTEREST_DEFAULT_TENTHS,
    LEV_MID_DEFAULT,
    LEV_PRO_DEFAULT,
    UserSettings,
    name_key,
)

SCHEMA_VERSION = 1

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
