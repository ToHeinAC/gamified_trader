import json
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from app import universe
from app.config import load_config
from app.db import Database
from app.fmt import date_de
from app.settings_rules import UserSettings
from app.ui.root import root
from tests.helpers import make_game_env


def _rendered_text(user: User) -> str:
    assert user.client is not None
    parts: list[str] = []
    for el in user.client.layout.descendants():
        parts.append(json.dumps(el.props, default=str))
        parts.append(str(getattr(el, "text", "")))
    return "\n".join(parts)


@pytest.fixture
async def gt_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[User]:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    async with user_simulation(root=root) as user:
        yield user


async def test_leak_before_confirmation(
    gt_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(universe, "ticker_names", lambda: {"ZZLEAK": "Leckprüfung AG"})
    cfg, _store, user_id = make_game_env(tmp_path, tickers=("ZZLEAK",), n=5, seed=1)

    await gt_user.open("/")

    db = Database(cfg.db_path)
    rnd = db.open_round(user_id)
    assert rnd is not None

    text = _rendered_text(gt_user)
    assert "ZZLEAK" not in text
    assert "Leckprüfung AG" not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert date_de(rnd.t0) not in text


async def test_reveal_after_confirmation(
    gt_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(universe, "ticker_names", lambda: {"ZZLEAK": "Leckprüfung AG"})
    cfg, _store, user_id = make_game_env(tmp_path, tickers=("ZZLEAK",), n=5, seed=1)
    await gt_user.open("/")
    db = Database(cfg.db_path)
    rnd = db.open_round(user_id)
    assert rnd is not None

    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    await gt_user.should_see("ZZLEAK")
    await gt_user.should_see("Leckprüfung AG")
    await gt_user.should_see(date_de(rnd.t0))


async def test_reload_keeps_the_round(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=2)
    db = Database(cfg.db_path)

    await gt_user.open("/")
    rnd1 = db.open_round(user_id)
    await gt_user.open("/")
    rnd2 = db.open_round(user_id)

    assert rnd1 is not None
    assert rnd2 is not None
    assert rnd1.id == rnd2.id


async def test_confirm_is_final(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=3)
    db = Database(cfg.db_path)

    await gt_user.open("/")
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    with pytest.raises(AssertionError):
        gt_user.find(marker="confirm")

    user_before = db.user(user_id)
    assert user_before is not None
    await gt_user.open("/")
    user_after = db.user(user_id)
    assert user_after is not None
    assert user_after.balance_cents == user_before.balance_cents
    assert db.stats(user_id).rounds == 1


async def test_level_change(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=4)
    db = Database(cfg.db_path)

    await gt_user.open("/")
    next(iter(gt_user.find(kind=ui.toggle, marker="level").elements)).set_value("Profi")
    await gt_user.should_see("Hebel 10")

    gt_user.find(marker="pick-K30").click()
    gt_user.find(marker="confirm").click()

    done = db.last_round(user_id)
    assert done is not None
    assert done.level == "Profi"
    assert done.leverage == 10


async def test_settings_change_while_open(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=5)
    db = Database(cfg.db_path)

    await gt_user.open("/")
    db.update_settings(user_id, UserSettings(10_000, 5, 15, 50, 20))
    await gt_user.open("/")
    next(iter(gt_user.find(kind=ui.toggle, marker="level").elements)).set_value("Profi")
    await gt_user.should_see("Hebel 15")


async def test_k_locked(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=6)
    db = Database(cfg.db_path)
    with sqlite3.connect(db.path) as conn:
        conn.execute("UPDATE users SET balance_cents = 9900 WHERE id = ?", (user_id,))

    await gt_user.open("/")
    await gt_user.should_see("Kaufoptionen gesperrt")
    btn = next(iter(gt_user.find(kind=ui.button, marker="pick-K10").elements))
    assert btn.enabled is False


async def test_next_round(gt_user: User, tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=7)
    db = Database(cfg.db_path)

    await gt_user.open("/")
    first = db.open_round(user_id)
    assert first is not None
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()
    gt_user.find("Nächste Runde").click()

    second = db.open_round(user_id)
    assert second is not None
    assert second.snapshot_id != first.snapshot_id


async def test_pool_missing_shows_hint(gt_user: User, tmp_path: Path) -> None:
    db = Database(load_config({"GT_DATA_DIR": str(tmp_path)}).db_path)
    db.init()
    db.create_user("Test", 10_000, "2026-09-22T10:00:00+00:00")

    await gt_user.open("/")
    await gt_user.should_see("gt snapshots build")
