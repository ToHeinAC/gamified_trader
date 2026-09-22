import sqlite3
from pathlib import Path

import pytest

from app.db import SCHEMA_VERSION, Database
from app.settings_rules import UserSettings

NOW = "2026-09-22T10:00:00+00:00"


def test_init_creates_tables_and_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    assert db.schema_version() == SCHEMA_VERSION
    db.init()
    assert db.schema_version() == SCHEMA_VERSION


def test_create_and_read_defaults(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    user = db.user(user_id)
    assert user is not None
    assert user.name == "Anna"
    assert user.lev_mid == 5
    assert user.lev_pro == 10
    assert user.interest_tenths == 50
    assert user.fee_tenths == 20
    assert user.balance_cents == user.start_capital_cents == 1_000_000
    assert db.active_user_id() == user_id


def test_unique_name_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    db.create_user("Anna", 10_000, NOW)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("ANNA", 10_000, NOW)


def test_negative_balance_check(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    with pytest.raises(sqlite3.IntegrityError), sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE users SET balance_cents = -1 WHERE id = ?", (user_id,))


def test_settings_do_not_touch_balance(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    with sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE users SET balance_cents = 500000 WHERE id = ?", (user_id,))

    db.update_settings(user_id, UserSettings(20_000, 5, 10, 50, 20))

    user = db.user(user_id)
    assert user is not None
    assert user.start_capital_cents == 2_000_000
    assert user.balance_cents == 500_000


def test_reset_balance(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    user_id = db.create_user("Anna", 10_000, NOW)
    with sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE users SET balance_cents = 500000 WHERE id = ?", (user_id,))

    db.reset_balance(user_id, NOW)

    user = db.user(user_id)
    assert user is not None
    assert user.balance_cents == 1_000_000
    assert db.reset_count(user_id) == 1

    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM resets WHERE user_id = ?", (user_id,)).fetchone()
    assert row["balance_before_cents"] == 500_000
    assert row["at"] == NOW


def test_users_ordered_by_name_key(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    db.init()
    db.create_user("Bert", 10_000, NOW)
    db.create_user("anna", 10_000, NOW)
    names = [u.name for u in db.users()]
    assert names == ["anna", "Bert"]


def test_active_user_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    db1 = Database(path)
    db1.init()
    user_id = db1.create_user("Anna", 10_000, NOW)

    db2 = Database(path)
    assert db2.active_user_id() == user_id
