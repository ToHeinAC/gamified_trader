"""Tests for app.ml.build_feature_frame."""

from pathlib import Path

import pandas as pd
import pytest

from app.features import FEATURE_COLUMNS, STOCK_FEATURES, compute_features
from app.indicators import with_indicators
from app.market import MARKET_COLUMNS, market_frame
from app.ml import build_feature_frame
from app.pool import build_pool
from app.price_store import PriceStore
from app.signals import signal_flags
from tests.helpers import random_walk_bars, write_store


@pytest.fixture
def small_pool(tmp_path: Path) -> tuple[pd.DataFrame, PriceStore]:
    tickers = ["AAA", "BBB", "CCC"]
    frames = {t: random_walk_bars(1600, seed=i) for i, t in enumerate(tickers)}
    store = write_store(tmp_path, frames)
    pool_df, _report = build_pool(tickers, store.read, n=60, seed=1)
    return pool_df, store


def _market(store: PriceStore) -> pd.DataFrame:
    return market_frame(store.tickers(), store.read, min_tickers=2)


def test_row_count_and_columns(small_pool: tuple[pd.DataFrame, PriceStore]) -> None:
    pool_df, store = small_pool
    features = build_feature_frame(pool_df, store.read, _market(store))
    assert len(features) == len(pool_df)
    assert set(features.columns) == {"snapshot_id", "t0", "t_end"} | set(FEATURE_COLUMNS)


def test_order_matches_pool_df(small_pool: tuple[pd.DataFrame, PriceStore]) -> None:
    pool_df, store = small_pool
    features = build_feature_frame(pool_df, store.read, _market(store))
    assert features["snapshot_id"].tolist() == pool_df["snapshot_id"].tolist()


def test_values_match_direct_feature_computation(
    small_pool: tuple[pd.DataFrame, PriceStore],
) -> None:
    pool_df, store = small_pool
    features = build_feature_frame(pool_df, store.read, _market(store))

    for pos in (0, len(pool_df) // 2, len(pool_df) - 1):
        snap = pool_df.iloc[pos]
        bars = store.read(str(snap["ticker"]))
        ind = with_indicators(bars)
        expected = compute_features(ind, signal_flags(ind)).iloc[int(snap["n_hist"]) - 1]
        actual = features.iloc[pos]
        for col in STOCK_FEATURES:
            a, b = actual[col], expected[col]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b, abs=1e-9), col


def test_t_end_is_120_bars_after_t0(small_pool: tuple[pd.DataFrame, PriceStore]) -> None:
    pool_df, store = small_pool
    features = build_feature_frame(pool_df, store.read, _market(store))
    snap = pool_df.iloc[0]
    bars = store.read(str(snap["ticker"]))
    i = int(snap["n_hist"]) - 1
    expected_t_end = pd.Timestamp(bars["date"].iloc[i + 120])
    assert features.iloc[0]["t_end"] == expected_t_end


def test_market_columns_are_the_row_at_t0(small_pool: tuple[pd.DataFrame, PriceStore]) -> None:
    pool_df, store = small_pool
    market = _market(store)
    features = build_feature_frame(pool_df, store.read, market)
    for pos in (0, len(pool_df) - 1):
        t0 = pd.Timestamp(pool_df.iloc[pos]["t0"])
        expected = market.loc[t0, list(MARKET_COLUMNS)].to_numpy(dtype=float).tolist()
        actual = features.loc[pos, list(MARKET_COLUMNS)].to_numpy(dtype=float).tolist()
        assert actual == pytest.approx(expected, nan_ok=True)
    rs = features["ret_60"] - features["mkt_ret_60"]
    assert features["rs_60"].tolist() == pytest.approx(rs.tolist(), nan_ok=True)
