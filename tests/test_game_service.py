import logging
import random
from pathlib import Path

import pytest

from app.db import Database
from app.game import setting_for
from app.game_service import GameService, PoolMissingError
from app.settings_rules import UserSettings
from app.trading import Level, OptionCode, make_card, option_values, simulate
from tests.helpers import make_game_env


def test_booking_with_user_values(tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=5)
    db = Database(cfg.db_path)
    db.update_settings(user_id, UserSettings(10_000, 3, 7, 40, 15))

    service = GameService(cfg, db, rng=random.Random(1))
    rnd = service.start_round(user_id)
    data = service.load(rnd.ticker, rnd.t0)
    user = db.user(user_id)
    assert user is not None

    ok = service.confirm(user, rnd, Level.PROFI, OptionCode.K30)
    assert ok

    done = db.last_round(user_id)
    assert done is not None
    assert done.leverage == 7
    assert done.fee_tenths == 15
    assert done.interest_tenths == 40

    setting = setting_for(user, Level.PROFI)
    card = make_card(30, data.snap.p0, data.snap.atr, setting.balance, 7, setting.costs)
    result = simulate(card, data.snap.future)
    values = option_values({30: result}, setting.balance)

    assert done.pnl_cents == round(result.pnl * 100)
    assert done.v == pytest.approx(values[OptionCode.K30])


def test_open_round_survives_restart(tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=2)
    db1 = Database(cfg.db_path)
    service1 = GameService(cfg, db1, rng=random.Random(1))
    rnd = service1.start_round(user_id)

    db2 = Database(cfg.db_path)
    service2 = GameService(cfg, db2)
    current = service2.current(user_id)
    assert current is not None
    assert current.snapshot_id == rnd.snapshot_id


def test_missing_price_file_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg, store, user_id = make_game_env(tmp_path, seed=3)
    store.path("ZZB").unlink()

    db = Database(cfg.db_path)
    service = GameService(cfg, db, rng=random.Random(1))
    user = db.user(user_id)
    assert user is not None

    with caplog.at_level(logging.WARNING):
        for _ in range(20):
            rnd = service.start_round(user_id)
            assert rnd.ticker != "ZZB"
            service.confirm(user, rnd, Level.EINFACH, OptionCode.W10)
    assert "übersprungen" in caplog.text


def test_pool_missing_raises(tmp_path: Path) -> None:
    from app.config import load_config

    cfg = load_config({"GT_DATA_DIR": str(tmp_path)})
    db = Database(cfg.db_path)
    db.init()
    user_id = db.create_user("Test", 10_000, "2026-09-22T10:00:00+00:00")

    service = GameService(cfg, db)
    with pytest.raises(PoolMissingError):
        service.start_round(user_id)


def test_resolution_is_deterministic(tmp_path: Path) -> None:
    cfg, _store, user_id = make_game_env(tmp_path, seed=4)
    db = Database(cfg.db_path)
    service = GameService(cfg, db, rng=random.Random(1))
    rnd = service.start_round(user_id)
    user = db.user(user_id)
    assert user is not None
    service.confirm(user, rnd, Level.EINFACH, OptionCode.W10)

    done = db.last_round(user_id)
    assert done is not None
    user_after = db.user(user_id)
    assert user_after is not None

    res = service.resolution(done, user_after)
    chosen = res.outcomes[res.chosen]
    assert chosen.value == pytest.approx(done.v)
    assert chosen.points == done.points
