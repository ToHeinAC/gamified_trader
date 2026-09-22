import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from app.config import load_config
from app.db import Database
from app.ui.root import root


@pytest.fixture
async def gt_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[User]:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    async with user_simulation(root=root) as user:
        yield user


def _db(tmp_path: Path) -> Database:
    return Database(load_config({"GT_DATA_DIR": str(tmp_path)}).db_path)


async def test_create_user(gt_user: User, tmp_path: Path) -> None:
    await gt_user.open("/setup")
    next(iter(gt_user.find(kind=ui.input, marker="name").elements)).set_value("Anna")
    next(iter(gt_user.find(kind=ui.number, marker="new-capital").elements)).set_value(20_000)
    gt_user.find("Anlegen").click()

    await gt_user.should_see("Anna")
    db = _db(tmp_path)
    assert [u.name for u in db.users()] == ["Anna"]


async def test_invalid_name_shows_message_and_creates_no_row(gt_user: User, tmp_path: Path) -> None:
    await gt_user.open("/setup")
    next(iter(gt_user.find(kind=ui.number, marker="new-capital").elements)).set_value(20_000)
    gt_user.find("Anlegen").click()

    await gt_user.should_see("Name muss 1\u201340 Zeichen lang sein.")
    assert _db(tmp_path).users() == []


async def test_settings_error_leaves_db_unchanged(gt_user: User, tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.init()
    db.create_user("Anna", 10_000, "2026-09-22T10:00:00+00:00")

    await gt_user.open("/setup")
    next(iter(gt_user.find(kind=ui.number, marker="lev-mid").elements)).set_value(12)
    next(iter(gt_user.find(kind=ui.number, marker="lev-pro").elements)).set_value(10)
    gt_user.find("Speichern").click()

    await gt_user.should_see("Hebel müssen ganze Zahlen von 2 bis 20 sein, Mittel ≤ Profi.")
    user = db.users()[0]
    assert (user.lev_mid, user.lev_pro) == (5, 10)


async def test_settings_saved(gt_user: User, tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.init()
    db.create_user("Anna", 10_000, "2026-09-22T10:00:00+00:00")

    await gt_user.open("/setup")
    next(iter(gt_user.find(kind=ui.number, marker="fee").elements)).set_value(2.5)
    gt_user.find("Speichern").click()

    await gt_user.should_see("Gespeichert")
    assert db.users()[0].fee_tenths == 25


async def test_reset_needs_confirmation(gt_user: User, tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.init()
    user_id = db.create_user("Anna", 10_000, "2026-09-22T10:00:00+00:00")
    with sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE users SET balance_cents = 500000 WHERE id = ?", (user_id,))

    await gt_user.open("/setup")
    gt_user.find("Guthaben zurücksetzen").click()
    gt_user.find(marker="cancel-reset").click()
    user_after_cancel = db.user(user_id)
    assert user_after_cancel is not None
    assert user_after_cancel.balance_cents == 500_000

    gt_user.find("Guthaben zurücksetzen").click()
    gt_user.find(marker="confirm-reset").click()
    await gt_user.should_see("Zurückgesetzt: 1-mal")
    user_after_reset = db.user(user_id)
    assert user_after_reset is not None
    assert user_after_reset.balance_cents == 1_000_000


async def test_setup_cards_paired_for_desktop(gt_user: User, tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.init()
    db.create_user("Anna", 10_000, "2026-09-22T10:00:00+00:00")

    await gt_user.open("/setup")
    row1 = next(iter(gt_user.find(marker="setup-row-1").elements))
    row2 = next(iter(gt_user.find(marker="setup-row-2").elements))
    assert "lg:grid-cols-2" in row1.classes
    assert "lg:grid-cols-2" in row2.classes


async def test_preselected_after_restart(gt_user: User, tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.init()
    db.create_user("Anna", 10_000, "2026-09-22T10:00:00+00:00")
    second_id = db.create_user("Bert", 10_000, "2026-09-22T10:00:01+00:00")

    await gt_user.open("/setup")
    select = next(iter(gt_user.find(kind=ui.select, marker="active-user").elements))
    assert select.value == second_id
