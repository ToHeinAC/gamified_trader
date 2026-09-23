import json
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from app import discover_service, universe
from app.config import load_config
from app.db import Database
from app.discover import ModelBundle
from app.features import FEATURE_COLUMNS
from app.fmt import date_de
from app.market import MARKET_COLUMNS
from app.ml import HORIZONS, LEVELS, QUANTILES
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


async def test_decision_layout_has_desktop_breakpoint_classes(
    gt_user: User, tmp_path: Path
) -> None:
    make_game_env(tmp_path, seed=4)
    await gt_user.open("/")

    layout = next(iter(gt_user.find(marker="decision-layout").elements))
    assert "flex-col" in layout.classes
    assert "lg:flex-row" in layout.classes
    # Quasar's own `.flex` utility sets `flex-wrap: wrap`, which collides with Tailwind's
    # `.flex` (no wrap) and would stack the panes even at lg: width; force nowrap explicitly.
    assert "lg:flex-nowrap" in layout.classes

    chart_pane = next(iter(gt_user.find(marker="decision-chart-pane").elements))
    assert "lg:w-[64%]" in chart_pane.classes

    options_pane = next(iter(gt_user.find(marker="decision-options-pane").elements))
    assert "lg:w-[36%]" in options_pane.classes

    plot = next(iter(gt_user.find(kind=ui.plotly).elements))
    assert "h-[420px]" in plot.classes
    assert "lg:h-[720px]" in plot.classes


async def test_picked_card_gets_selected_marker_class(gt_user: User, tmp_path: Path) -> None:
    make_game_env(tmp_path, seed=7)
    await gt_user.open("/")

    gt_user.find(marker="pick-W10").click()

    picked_btn = next(iter(gt_user.find(marker="pick-W10").elements))
    card = picked_btn.parent_slot.parent if picked_btn.parent_slot else None
    assert card is not None
    assert "gt-selected" in card.classes

    other_btn = next(iter(gt_user.find(marker="pick-K10").elements))
    other_card = other_btn.parent_slot.parent if other_btn.parent_slot else None
    assert other_card is not None
    assert "gt-selected" not in other_card.classes


async def test_resolution_view_uses_desktop_grid_layout(gt_user: User, tmp_path: Path) -> None:
    make_game_env(tmp_path, seed=8)
    await gt_user.open("/")
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    layout = next(iter(gt_user.find(marker="resolution-layout").elements))
    assert "gt-resolution-grid" in layout.classes

    for marker, area in (
        ("resolution-tiles-pane", "gt-area-tiles"),
        ("resolution-chart-pane", "gt-area-chart"),
        ("resolution-result-pane", "gt-area-result"),
        ("resolution-next-pane", "gt-area-next"),
        ("resolution-stats-pane", "gt-area-stats"),
    ):
        pane = next(iter(gt_user.find(marker=marker).elements))
        assert area in pane.classes

    await gt_user.should_see("Guthaben:")
    await gt_user.should_see("Punkte gesamt:")
    await gt_user.should_see("Nächste Runde")
    await gt_user.should_see("Optimal:")


async def test_resolution_shows_result_badge(gt_user: User, tmp_path: Path) -> None:
    make_game_env(tmp_path, seed=8)
    await gt_user.open("/")
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    badge = next(iter(gt_user.find(marker="result-badge").elements))
    tier_classes = {"gt-badge-optimal", "gt-badge-gut", "gt-badge-neutral", "gt-badge-schlecht"}
    matched = tier_classes & set(badge.classes)
    assert len(matched) == 1
    tier = next(iter(matched)).removeprefix("gt-badge-")
    label = {
        "optimal": "Optimal!",
        "gut": "Gut gemacht",
        "neutral": "Neutral",
        "schlecht": "Nicht optimal",
    }[tier]
    await gt_user.should_see(label)


class _FakeModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x: pd.DataFrame) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
        return np.full(len(x), self.value, dtype=np.float64)


async def test_resolution_shows_ml_top3(
    gt_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_game_env(tmp_path, seed=8)
    models = {
        (lev, h, q): _FakeModel(0.01 * lev + h / 1000 + q / 10)
        for lev in LEVELS
        for h in HORIZONS
        for q in QUANTILES
    }
    bundle = ModelBundle(models=models, meta={"feature_columns": list(FEATURE_COLUMNS)})
    dates = pd.date_range("1990-01-01", "2030-12-31", freq="D", name="date")
    market = pd.DataFrame({c: 0.0 for c in MARKET_COLUMNS}, index=dates)
    monkeypatch.setattr(discover_service, "load_bundle", lambda c: bundle)
    monkeypatch.setattr(discover_service, "load_market", lambda c: market)

    await gt_user.open("/")
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    await gt_user.should_see("ML-Strategie")
    table = next(iter(gt_user.find(marker="ml-strategy-table").elements))
    assert isinstance(table, ui.table)
    rows = table.rows
    assert [r["option"] for r in rows] == ["K120 · Mittel", "K120 · Einfach", "K30 · Mittel"]
    assert [r["rang"] for r in rows] == [1, 2, 3]
    await gt_user.should_see("Empfehlung: K120 · Mittel")


async def test_resolution_ml_hint_without_model(gt_user: User, tmp_path: Path) -> None:
    make_game_env(tmp_path, seed=8)
    await gt_user.open("/")
    gt_user.find(marker="pick-W10").click()
    gt_user.find(marker="confirm").click()

    await gt_user.should_see("Kein ML-Modell verfügbar")


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
