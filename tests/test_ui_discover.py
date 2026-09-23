"""UI tests for page "Entdecken" (PRD M8)."""

from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from app import discover_service, yahoo
from app.discover import ModelBundle
from app.features import FEATURE_COLUMNS
from app.ml import HORIZONS, LEVELS, QUANTILES
from app.settings_rules import UserSettings
from app.ui.root import root
from tests.helpers import random_walk_bars

_MARKET_COLUMNS = (
    "mkt_ret_20",
    "mkt_ret_60",
    "mkt_ret_250",
    "mkt_dist_sma200",
    "mkt_vola20",
    "mkt_breadth200",
)


@pytest.fixture
async def gt_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[User]:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    async with user_simulation(root=root) as user:
        yield user


class _FakeModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x: pd.DataFrame) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
        return np.full(len(x), self.value, dtype=np.float64)


def _fake_bundle(monkeypatch: pytest.MonkeyPatch, *, buy: bool = True, beats: bool = True) -> None:
    scores = (0.01, 0.05, 0.10) if buy else (-0.05, 0.0, 0.03)
    models: dict[tuple[int, int, float], _FakeModel] = {}
    for lev in LEVELS:
        for h in HORIZONS:
            for q, v in zip(QUANTILES, scores, strict=True):
                models[(lev, h, q)] = _FakeModel(v)
    meta: dict[str, object] = {
        "feature_columns": list(FEATURE_COLUMNS),
        "importance": {"ret_5": 0.5, "rsi": 0.3, "atr_pct": 0.2, "ret_20": 0.1, "vola20": 0.05},
        "beats_baselines": {"never": beats, "k120_l1": beats, "k120_l5": beats},
        "growth_model": 0.003,
        "growth_baselines": {"never": 0.0, "k120_l1": 0.001, "k120_l5": 0.004},
    }
    bundle = ModelBundle(models=models, meta=meta)
    monkeypatch.setattr(discover_service, "load_bundle", lambda cfg: bundle)


def _fake_market(monkeypatch: pytest.MonkeyPatch, last_date: pd.Timestamp) -> None:
    idx = pd.DatetimeIndex([last_date], name="date")
    market = pd.DataFrame({col: [0.0] for col in _MARKET_COLUMNS}, index=idx)
    monkeypatch.setattr(discover_service, "load_market", lambda cfg: market)


def _fake_history(monkeypatch: pytest.MonkeyPatch) -> pd.DataFrame:
    bars = random_walk_bars(300, seed=1)
    monkeypatch.setattr(yahoo, "fetch_history", lambda t: bars)
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: "EQUITY")
    monkeypatch.setattr(discover_service, "load_pool_features", lambda cfg: None)
    return bars


async def test_nav_link_and_disclaimer(gt_user: User) -> None:
    await gt_user.open("/")
    await gt_user.should_see("Entdecken")

    await gt_user.open("/entdecken")
    await gt_user.should_see(marker="disclaimer")


async def test_invalid_ticker_shows_hint_without_adapter_call(
    gt_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(yahoo, "fetch_history", lambda t: calls.append(t) or None)

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("../x")
    gt_user.find(marker="load").click()

    await gt_user.should_see("Ungültiges Tickersymbol.", retries=30)
    assert calls == []


async def test_unknown_ticker_shows_error_and_no_chart(
    gt_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(yahoo, "fetch_history", lambda t: None)

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("ZZZZ")
    gt_user.find(marker="load").click()

    await gt_user.should_see("Keine Kursdaten", retries=30)
    with pytest.raises(AssertionError):
        gt_user.find(kind=ui.plotly)


async def test_ok_path_shows_recommendation_and_chart(
    gt_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = _fake_history(monkeypatch)
    _fake_bundle(monkeypatch, buy=True, beats=True)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see(marker="recommendation", retries=30)
    await gt_user.should_see(marker="quantile-table")
    await gt_user.should_see(marker="top-features")
    plots = gt_user.find(kind=ui.plotly).elements
    assert len(plots) == 1
    figure_json = str(next(iter(plots)).props["options"])
    assert "AAPL" in figure_json


async def test_not_equity_shows_hint(gt_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    bars = random_walk_bars(300, seed=2)
    monkeypatch.setattr(yahoo, "fetch_history", lambda t: bars)
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: "ETF")
    monkeypatch.setattr(discover_service, "load_pool_features", lambda cfg: None)
    _fake_bundle(monkeypatch)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("SPY")
    gt_user.find(marker="load").click()

    await gt_user.should_see("Modell nur auf Aktien trainiert", retries=30)


async def test_no_model_shows_hint(gt_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_history(monkeypatch)
    monkeypatch.setattr(discover_service, "load_bundle", lambda cfg: None)

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see("gt model train", retries=30)


async def test_market_stale_shows_hint(gt_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_history(monkeypatch)
    _fake_bundle(monkeypatch)
    monkeypatch.setattr(discover_service, "load_market", lambda cfg: None)

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see("gt data update", retries=30)


async def test_baseline_hint_shown_when_not_beating_all(
    gt_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = _fake_history(monkeypatch)
    _fake_bundle(monkeypatch, buy=True, beats=False)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see(
        "Das Modell schlägt nicht jede einfache Vergleichsstrategie.", retries=30
    )


async def test_a22_hint_for_nonstandard_leverage(
    gt_user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config import load_config
    from app.db import Database

    cfg = load_config({"GT_DATA_DIR": str(tmp_path)})
    db = Database(cfg.db_path)
    db.init()
    user_id = db.create_user("Test", 10_000, "2026-09-22T10:00:00+00:00")
    db.set_active_user(user_id)
    db.update_settings(user_id, UserSettings(10_000, 3, 10, 50, 20))

    bars = _fake_history(monkeypatch)
    _fake_bundle(monkeypatch, buy=True, beats=True)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see("Modell mit Hebel 1/5 und Standardkosten trainiert", retries=30)


async def test_no_user_shows_setup_hint_and_no_card(
    gt_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = _fake_history(monkeypatch)
    _fake_bundle(monkeypatch, buy=True, beats=True)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL")
    gt_user.find(marker="load").click()

    await gt_user.should_see("zuerst im Setup einen Nutzer anlegen", retries=30)


async def test_enter_key_triggers_load(gt_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    bars = _fake_history(monkeypatch)
    _fake_bundle(monkeypatch, buy=True, beats=True)
    _fake_market(monkeypatch, bars["date"].iloc[-1])

    await gt_user.open("/entdecken")
    gt_user.find(marker="ticker-input").type("AAPL").trigger("keydown.enter")

    await gt_user.should_see(marker="recommendation", retries=30)
