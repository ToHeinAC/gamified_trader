"""Tests for app.features (PRD R12)."""

import numpy as np
import pandas as pd
import pytest

from app.features import FEATURE_COLUMNS, STOCK_FEATURES, compute_features, with_market
from app.indicators import with_indicators
from app.market import MARKET_COLUMNS
from app.signals import EVENTS, signal_flags
from tests.helpers import make_bars, random_walk_bars


def _features_for(bars: pd.DataFrame) -> pd.DataFrame:
    ind = with_indicators(bars)
    flags = signal_flags(ind)
    return compute_features(ind, flags)


def test_feature_columns_count() -> None:
    assert len(STOCK_FEATURES) == 29
    assert len(FEATURE_COLUMNS) == 37
    assert len(set(FEATURE_COLUMNS)) == 37
    assert FEATURE_COLUMNS[:29] == STOCK_FEATURES


def test_hand_computed_values() -> None:
    closes = [100.0 + i * 0.1 for i in range(60)]
    bars = make_bars(closes)
    feats = _features_for(bars)

    t = 55
    expected_ret5 = closes[t] / closes[t - 5] - 1
    assert feats["ret_5"].iloc[t] == pytest.approx(expected_ret5, abs=1e-9)

    ind = with_indicators(bars)
    expected_dist_sma50 = closes[t] / ind["sma50"].iloc[t] - 1
    assert feats["dist_sma50"].iloc[t] == pytest.approx(expected_dist_sma50, abs=1e-9)

    expected_atr_pct = ind["atr14"].iloc[t] / closes[t]
    assert feats["atr_pct"].iloc[t] == pytest.approx(expected_atr_pct, abs=1e-9)

    upper, lower = ind["bb_upper"].iloc[t], ind["bb_lower"].iloc[t]
    expected_pctb = (closes[t] - lower) / (upper - lower)
    assert feats["bb_pctb"].iloc[t] == pytest.approx(expected_pctb, abs=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_causality(seed: int) -> None:
    bars = random_walk_bars(400, seed=seed)
    rng = np.random.default_rng(seed + 1000)
    t = int(rng.integers(260, 399))

    full = _features_for(bars)
    truncated = _features_for(bars.iloc[: t + 1])

    row_full = full.iloc[t]
    row_trunc = truncated.iloc[t]
    for col in STOCK_FEATURES:
        a, b = row_full[col], row_trunc[col]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == pytest.approx(b, abs=1e-9), col


def test_short_history_is_nan() -> None:
    bars = random_walk_bars(200, seed=1)
    feats = _features_for(bars)
    assert feats["ret_250"].isna().all()
    assert feats["dist_high252"].isna().all()

    bars_short = random_walk_bars(100, seed=1)
    feats_short = _features_for(bars_short)
    assert feats_short["bb_width_rank"].isna().all()


def test_bb_width_rank_defined_after_126_valid_widths() -> None:
    bars = random_walk_bars(400, seed=2)
    feats = _features_for(bars)
    # bb_width needs 20 bars, then 126 more valid values -> first defined at index 19 + 125 = 144
    assert feats["bb_width_rank"].iloc[143:145].isna().tolist() == [True, False]


def test_constant_prices_no_warning(recwarn: pytest.WarningsRecorder) -> None:
    bars = make_bars([100.0] * 60)
    feats = _features_for(bars)
    assert feats["bb_width"].iloc[59] == pytest.approx(0.0, abs=1e-9)
    assert pd.isna(feats["bb_pctb"].iloc[59])
    assert not any("divide" in str(w.message) or "invalid" in str(w.message) for w in recwarn.list)


def test_zero_volume_no_error() -> None:
    bars = make_bars([100.0 + i * 0.05 for i in range(60)], volume=0)
    feats = _features_for(bars)
    assert feats["vol_rel"].isna().all()


def test_sig_columns_are_float_flags() -> None:
    bars = random_walk_bars(300, seed=3)
    feats = _features_for(bars)
    for event in EVENTS:
        col = feats[f"sig_{event}"]
        assert set(col.dropna().unique().tolist()) <= {0.0, 1.0}


def _market(dates: list[str], ret_60: list[float]) -> pd.DataFrame:
    mkt = pd.DataFrame(
        {col: [float(i) for i in range(len(dates))] for col in MARKET_COLUMNS},
        index=pd.DatetimeIndex(pd.to_datetime(dates), name="date"),
    )
    mkt["mkt_ret_60"] = ret_60
    return mkt


def test_with_market_exact_and_backward_match() -> None:
    market = _market(["2020-01-02", "2020-01-06", "2020-01-08"], [0.01, 0.02, 0.03])
    stock = pd.DataFrame({col: [0.0, 0.0, 0.0] for col in STOCK_FEATURES})
    stock["ret_60"] = [0.10, 0.20, 0.30]
    stock["ret_250"] = [0.5, 0.5, 0.5]
    dates = pd.Series(pd.to_datetime(["2020-01-08", "2020-01-02", "2020-01-07"]))

    out = with_market(stock, dates, market)

    assert tuple(out.columns) == FEATURE_COLUMNS
    assert out["mkt_ret_60"].tolist() == pytest.approx([0.03, 0.01, 0.02])  # 01-07 -> 01-06 row
    assert out["mkt_ret_20"].tolist() == pytest.approx([2.0, 0.0, 1.0])
    assert out["rs_60"].tolist() == pytest.approx([0.07, 0.19, 0.28])
    assert out["ret_60"].tolist() == pytest.approx([0.10, 0.20, 0.30])  # order preserved


def test_with_market_before_first_market_row_is_nan() -> None:
    market = _market(["2020-01-06"], [0.01])
    stock = pd.DataFrame({col: [0.0] for col in STOCK_FEATURES})
    out = with_market(stock, pd.Series(pd.to_datetime(["2020-01-02"])), market)
    assert out[list(MARKET_COLUMNS)].isna().all(axis=None)
    assert pd.isna(out["rs_60"].iloc[0])
