import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from app.db import SCHEMA_VERSION, Database

NOW = "2026-09-22T10:00:00+00:00"
T0 = date(2020, 5, 4)


@dataclass(frozen=True)
class _Outcome:
    level: str = "Einfach"
    leverage: int = 1
    fee_tenths: int = 20
    interest_tenths: int = 50
    option: str = "K30"
    v: float = 0.05
    pnl_cents: int = 5000
    fee_cents: int = 4000
    financing_cents: int = 0
    points: int = 100
    balance_after_cents: int = 1_050_000


def _v1_schema(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "name_key TEXT NOT NULL UNIQUE, start_capital_cents INTEGER NOT NULL, "
            "balance_cents INTEGER NOT NULL, lev_mid INTEGER NOT NULL, lev_pro INTEGER NOT NULL, "
            "interest_tenths INTEGER NOT NULL, fee_tenths INTEGER NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO users (name, name_key, start_capital_cents, balance_cents, lev_mid, "
            "lev_pro, interest_tenths, fee_tenths, created_at) "
            "VALUES ('Anna', 'anna', 1000000, 1000000, 5, 10, 50, 20, ?)",
            (NOW,),
        )
        conn.execute(
            "CREATE TABLE resets (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "at TEXT NOT NULL, balance_before_cents INTEGER NOT NULL)"
        )
        conn.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("PRAGMA user_version = 1")


def test_migration_v1_to_v2_keeps_user(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    _v1_schema(path)

    db = Database(path)
    db.init()

    assert db.schema_version() == SCHEMA_VERSION == 2
    with sqlite3.connect(path) as conn:
        conn.execute("SELECT * FROM rounds").fetchall()
    users = db.users()
    assert len(users) == 1
    assert users[0].name == "Anna"


def test_one_open_round_per_user(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    db.insert_open_round(user_id, "snap1", "AAA", T0, NOW)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_open_round(user_id, "snap2", "BBB", T0, NOW)


def test_confirm_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    rnd = db.insert_open_round(user_id, "snap1", "AAA", T0, NOW)

    calls = []

    def outcome(before: int) -> _Outcome:
        calls.append(before)
        return _Outcome()

    assert db.confirm_round(rnd.id, user_id, outcome, NOW) is True
    assert db.confirm_round(rnd.id, user_id, outcome, NOW) is False
    assert len(calls) == 1

    user = db.user(user_id)
    assert user is not None
    assert user.balance_cents == 1_050_000

    done = db.last_round(user_id)
    assert done is not None
    assert done.status == "done"
    assert done.points == 100


def test_play_counts_and_stats(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)

    rnd1 = db.insert_open_round(user_id, "snap1", "AAA", T0, NOW)
    db.confirm_round(rnd1.id, user_id, lambda _b: _Outcome(points=100), NOW)
    rnd2 = db.insert_open_round(user_id, "snap1", "AAA", T0, NOW)
    db.confirm_round(rnd2.id, user_id, lambda _b: _Outcome(points=50), NOW)

    counts = db.play_counts(user_id)
    assert counts == {"snap1": 2}

    stats = db.stats(user_id)
    assert stats.rounds == 2
    assert stats.points_total == 150
    assert stats.points_avg == 75.0
    assert stats.optimal_share == 0.5
    assert stats.resets == 0
