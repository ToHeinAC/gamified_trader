"""Tests for app.discover (PRD M8): pure ticker/status rules and analysis."""

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import pytest

from app import discover, universe
from app.db import UserRow
from app.discover_store import MetaEntry
from app.features import FEATURE_COLUMNS
from app.indicators import with_indicators
from app.market import MARKET_COLUMNS
from app.ml import HORIZONS, LEVELS, QUANTILES, Recommendation
from app.trading import Level, OptionCode, make_card
from app.universe import UniverseEntry
from tests.helpers import make_bars, random_walk_bars


def _user(**overrides: object) -> UserRow:
    base: dict[str, object] = {
        "id": 1,
        "name": "Test",
        "start_capital_cents": 1_000_000,
        "balance_cents": 1_000_000,
        "lev_mid": 5,
        "lev_pro": 10,
        "interest_tenths": 50,
        "fee_tenths": 20,
    }
    base.update(overrides)
    return UserRow(**base)  # type: ignore[arg-type]


class _FakeModel:
    def __init__(self, value: float) -> None:
        self.value = value
        self.last_x: pd.DataFrame | None = None

    def predict(self, x: pd.DataFrame) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
        self.last_x = x
        return np.full(len(x), self.value, dtype=np.float64)


def _all_scores(
    overrides: Mapping[tuple[int, int], tuple[float, float, float]] | None = None,
) -> dict[tuple[int, int, float], _FakeModel]:
    base = {(lev, h): (-0.05, 0.0, 0.03) for lev in LEVELS for h in HORIZONS}
    if overrides:
        base.update(overrides)
    models: dict[tuple[int, int, float], _FakeModel] = {}
    for (lev, h), (p25, p50, p75) in base.items():
        for q, v in zip(QUANTILES, (p25, p50, p75), strict=True):
            models[(lev, h, q)] = _FakeModel(v)
    return models


def _bundle(
    models: Mapping[tuple[int, int, float], _FakeModel],
    *,
    feature_columns: Sequence[str] = FEATURE_COLUMNS,
    beats: Mapping[str, bool] | None = None,
) -> discover.ModelBundle:
    meta: dict[str, object] = {
        "feature_columns": list(feature_columns),
        "importance": {
            "ret_5": 0.5,
            "rsi": 0.3,
            "mkt_breadth200": 0.2,
            "ret_20": 0.1,
            "atr_pct": 0.05,
        },
        "beats_baselines": dict(beats)
        if beats is not None
        else {"never": True, "k120_l1": True, "k120_l5": True},
    }
    return discover.ModelBundle(models=models, meta=meta)


def _market(last: pd.Timestamp, offset_days: int = 0) -> pd.DataFrame:
    idx = pd.DatetimeIndex([last - pd.Timedelta(days=offset_days)], name="date")
    return pd.DataFrame({col: [0.0] for col in MARKET_COLUMNS}, index=idx)


# --- normalize_ticker --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" aapl ", "AAPL"),
        ("SAP.DE · SAP SE", "SAP.DE"),
        ("^GSPC", "^GSPC"),
        ("EURUSD=X", "EURUSD=X"),
        ("BTC-USD", "BTC-USD"),
    ],
)
def test_normalize_ticker_valid(text: str, expected: str) -> None:
    assert discover.normalize_ticker(text) == expected


@pytest.mark.parametrize(
    "text",
    ["../x", "A B", "", "...", "A" * 21],
)
def test_normalize_ticker_invalid(text: str) -> None:
    assert discover.normalize_ticker(text) is None


# --- suggestions / display_name ----------------------------------------------


def test_suggestions() -> None:
    entries = [
        UniverseEntry("AAPL", "Apple Inc.", "SP500"),
        UniverseEntry("SAP.DE", "SAP SE", "DAX"),
    ]
    assert discover.suggestions(entries) == ["AAPL · Apple Inc.", "SAP.DE · SAP SE"]


def test_display_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universe, "ticker_names", lambda: {"AAPL": "Apple Inc."})
    assert discover.display_name("AAPL") == "Apple Inc."
    assert discover.display_name("ZZZZ") == "ZZZZ"


# --- needs_fetch / completed_bars --------------------------------------------


def test_needs_fetch() -> None:
    from datetime import date

    today = date(2026, 9, 23)
    assert discover.needs_fetch(None, today) is True
    assert discover.needs_fetch(MetaEntry(fetched=today, quote_type="EQUITY"), today) is False
    assert (
        discover.needs_fetch(MetaEntry(fetched=date(2026, 9, 22), quote_type=None), today) is True
    )


def test_completed_bars_drops_today_and_later() -> None:
    from datetime import date

    bars = make_bars([10.0, 11.0, 12.0], start="2026-09-21")
    today = date(2026, 9, 23)  # 2026-09-23 is a bar's date (third row)
    out = discover.completed_bars(bars, today)
    assert len(out) == 2
    assert (out["date"] < pd.Timestamp(today)).all()


# --- beats_all / model_matches / needs_model_hint / market_fresh ------------


def test_beats_all() -> None:
    assert discover.beats_all({"beats_baselines": {"a": True, "b": True}}) is True
    assert discover.beats_all({"beats_baselines": {"a": True, "b": False}}) is False


def test_model_matches() -> None:
    assert discover.model_matches({"feature_columns": list(FEATURE_COLUMNS)}) is True
    assert discover.model_matches({"feature_columns": ["foo"]}) is False


def test_needs_model_hint() -> None:
    assert discover.needs_model_hint(_user()) is False
    assert discover.needs_model_hint(_user(lev_mid=3)) is True
    assert discover.needs_model_hint(_user(fee_tenths=10)) is True
    assert discover.needs_model_hint(_user(interest_tenths=10)) is True
    assert discover.needs_model_hint(_user(lev_pro=15)) is False


def test_market_fresh() -> None:
    tag0 = pd.Timestamp("2026-09-23")
    assert discover.market_fresh(_market(tag0, offset_days=5), tag0) is True
    assert discover.market_fresh(_market(tag0, offset_days=6), tag0) is False
    assert discover.market_fresh(None, tag0) is False
    assert discover.market_fresh(pd.DataFrame(columns=list(MARKET_COLUMNS)), tag0) is False


# --- top_features -------------------------------------------------------------


def test_top_features() -> None:
    meta: dict[str, object] = {
        "importance": {
            "ret_5": 0.9,
            "rsi": 0.5,
            "atr_pct": 0.3,
            "mkt_ret_20": 0.2,
            "vola20": 0.1,
            "dist_sma50": 0.05,
        }
    }
    row = pd.DataFrame(
        {
            "ret_5": [0.02],
            "rsi": [55.0],
            "atr_pct": [np.nan],
            "mkt_ret_20": [0.01],
            "vola20": [0.02],
        }
    )
    pool = pd.DataFrame({"ret_5": [0.0, 0.01, 0.02, 0.03], "rsi": [40.0, 50.0, 60.0, 70.0]})

    feats = discover.top_features(meta, row, pool)

    assert [f.name for f in feats] == ["ret_5", "rsi", "atr_pct", "mkt_ret_20", "vola20"]
    assert feats[0].value == pytest.approx(0.02)
    assert feats[0].percentile == pytest.approx(0.75)
    assert feats[2].value is None
    assert feats[2].percentile is None
    assert feats[3].value == pytest.approx(0.01)
    assert feats[3].percentile is None  # not a pool column


def test_top_features_no_pool() -> None:
    meta: dict[str, object] = {"importance": {"ret_5": 0.9}}
    row = pd.DataFrame({"ret_5": [0.02]})
    feats = discover.top_features(meta, row, None)
    assert feats[0].percentile is None


# --- analyze ------------------------------------------------------------------


def _ind(n: int = 300, seed: int = 1) -> pd.DataFrame:
    return with_indicators(random_walk_bars(n, seed=seed))


def test_analyze_too_short() -> None:
    ind = _ind(249)
    result = discover.analyze("AAA", ind, "EQUITY", None, None, None)
    assert result.status == discover.Status.TOO_SHORT
    assert result.recommendation is None


@pytest.mark.parametrize("quote_type", ["ETF", None])
def test_analyze_not_equity(quote_type: str | None) -> None:
    ind = _ind()
    bundle = _bundle(_all_scores())
    market = _market(pd.Timestamp(ind["date"].iloc[-1]))
    result = discover.analyze("AAA", ind, quote_type, bundle, market, None)
    assert result.status == discover.Status.NOT_EQUITY


def test_analyze_no_model() -> None:
    ind = _ind()
    result = discover.analyze("AAA", ind, "EQUITY", None, None, None)
    assert result.status == discover.Status.NO_MODEL


def test_analyze_model_mismatch() -> None:
    ind = _ind()
    bundle = _bundle(_all_scores(), feature_columns=["foo"])
    market = _market(pd.Timestamp(ind["date"].iloc[-1]))
    result = discover.analyze("AAA", ind, "EQUITY", bundle, market, None)
    assert result.status == discover.Status.MODEL_MISMATCH


def test_analyze_market_stale() -> None:
    ind = _ind()
    bundle = _bundle(_all_scores())
    stale_market = _market(pd.Timestamp(ind["date"].iloc[-1]), offset_days=6)
    assert discover.analyze("AAA", ind, "EQUITY", bundle, stale_market, None).status == (
        discover.Status.MARKET_STALE
    )
    assert discover.analyze("AAA", ind, "EQUITY", bundle, None, None).status == (
        discover.Status.MARKET_STALE
    )


def test_analyze_ok_recommendation_matches_ml_recommend() -> None:
    ind = _ind()
    models = _all_scores({(5, 30): (0.01, 0.05, 0.10)})
    bundle = _bundle(models)
    market = _market(pd.Timestamp(ind["date"].iloc[-1]))

    result = discover.analyze("AAA", ind, "EQUITY", bundle, market, None)

    assert result.status == discover.Status.OK
    assert result.recommendation is not None
    assert result.recommendation.option == OptionCode.K30
    assert result.recommendation.level == Level.MITTEL
    assert len(result.quantiles) == len(LEVELS) * len(HORIZONS)
    assert result.beats_all is True


def test_analyze_uses_same_features_as_training() -> None:
    from app.features import compute_features
    from app.signals import signal_flags

    ind = _ind()
    models = _all_scores()
    bundle = _bundle(models)
    market = _market(pd.Timestamp(ind["date"].iloc[-1]))

    discover.analyze("AAA", ind, "EQUITY", bundle, market, None)

    any_model = next(iter(models.values()))
    assert any_model.last_x is not None
    expected = discover.feature_row(ind, market)
    pd.testing.assert_frame_equal(any_model.last_x, expected[list(FEATURE_COLUMNS)])
    # sanity: it is indeed derived from compute_features's last completed row
    stock_expected = compute_features(ind, signal_flags(ind)).iloc[[-1]]
    for col in stock_expected.columns:
        a, b = expected[col].iloc[0], stock_expected[col].iloc[0]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == pytest.approx(b)


def test_analyze_only_sees_bars_up_to_tag0() -> None:
    from datetime import timedelta

    bars = random_walk_bars(300, seed=7)
    today = (bars["date"].iloc[-1] + timedelta(days=1)).date()
    extra = make_bars([float(bars["close"].iloc[-1]) * 1.05], start=str(today))
    bars_with_today = pd.concat([bars, extra], ignore_index=True)

    ind_a = with_indicators(discover.completed_bars(bars_with_today, today))
    ind_b = with_indicators(bars)
    pd.testing.assert_frame_equal(ind_a, ind_b)

    market = _market(pd.Timestamp(bars["date"].iloc[-1]))
    bundle = _bundle(_all_scores({(5, 30): (0.01, 0.05, 0.10)}))
    a = discover.analyze("AAA", ind_a, "EQUITY", bundle, market, None)
    b = discover.analyze("AAA", ind_b, "EQUITY", bundle, market, None)
    assert a.recommendation == b.recommendation


# --- recommendation_card -------------------------------------------------------


def test_recommendation_card_buy() -> None:
    ind = _ind()
    user = _user()
    rec = Recommendation(OptionCode.K30, Level.MITTEL, 0.01, 0.05, 0.10, 0.03)

    result = discover.recommendation_card(rec, ind, user)

    assert result is not None
    card, setting = result
    assert setting.leverage == 5
    expected = make_card(
        30,
        float(ind["close"].iloc[-1]),
        float(ind["atr14"].iloc[-1]),
        setting.balance,
        setting.leverage,
        setting.costs,
    )
    assert card == expected


def test_recommendation_card_wait_is_none() -> None:
    ind = _ind()
    rec = Recommendation(OptionCode.W30, Level.EINFACH, 0.0, 0.0, 0.0, -0.01)
    assert discover.recommendation_card(rec, ind, _user()) is None


def test_recommendation_card_no_user_is_none() -> None:
    ind = _ind()
    rec = Recommendation(OptionCode.K30, Level.MITTEL, 0.01, 0.05, 0.10, 0.03)
    assert discover.recommendation_card(rec, ind, None) is None


def test_recommendation_card_locked_balance_is_none() -> None:
    ind = _ind()
    rec = Recommendation(OptionCode.K30, Level.MITTEL, 0.01, 0.05, 0.10, 0.03)
    user = _user(balance_cents=100, start_capital_cents=1_000_000)
    assert discover.recommendation_card(rec, ind, user) is None


def test_recommendation_card_zero_atr_is_none() -> None:
    ind = _ind().copy()
    ind.loc[ind.index[-1], "atr14"] = 0.0
    rec = Recommendation(OptionCode.K30, Level.MITTEL, 0.01, 0.05, 0.10, 0.03)
    assert discover.recommendation_card(rec, ind, _user()) is None
