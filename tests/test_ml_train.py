"""End-to-end test for app.ml.train (PRD R14)."""

from typing import cast

import numpy as np
import pandas as pd
import pytest

from app.market import market_frame
from app.ml import HORIZONS, LEVELS, QUANTILES, TrainResult, train, train_all
from app.pool import build_pool
from app.price_store import PriceStore
from tests.helpers import random_walk_bars, write_store

MAX_ITER = 15  # keep the suite fast (docs/spec-m7-model.md §5)


@pytest.fixture(scope="module")
def small_pool(tmp_path_factory: pytest.TempPathFactory) -> tuple[pd.DataFrame, PriceStore]:
    tmp_path = tmp_path_factory.mktemp("ml_train_pool")
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    frames = {t: random_walk_bars(1600, seed=i) for i, t in enumerate(tickers)}
    store = write_store(tmp_path, frames)
    pool_df, _report = build_pool(tickers, store.read, n=120, seed=3)
    return pool_df, store


@pytest.fixture(scope="module")
def trained(small_pool: tuple[pd.DataFrame, PriceStore]) -> TrainResult:
    pool_df, store = small_pool
    return train(pool_df, store.read, _market(store), seed=42, max_iter=MAX_ITER)


def _market(store: PriceStore) -> pd.DataFrame:
    return market_frame(store.tickers(), store.read, min_tickers=2)


def test_train_produces_18_models(trained: TrainResult) -> None:
    assert len(trained.models) == len(LEVELS) * len(HORIZONS) * len(QUANTILES)
    for leverage in LEVELS:
        for horizon in HORIZONS:
            for q in QUANTILES:
                assert (leverage, horizon, q) in trained.models


def test_metadata_has_documented_keys(
    trained: TrainResult, small_pool: tuple[pd.DataFrame, PriceStore]
) -> None:
    pool_df, _store = small_pool
    expected_keys = {
        "feature_columns",
        "seed",
        "levels",
        "horizons",
        "quantiles",
        "n_snapshots",
        "data_as_of",
        "period",
        "hyperparameters",
        "growth_model",
        "growth_baselines",
        "beats_baselines",
        "fold_growth",
        "worst_fold_growth",
        "all_folds_positive",
        "traded_share",
        "booked_p5",
        "mean_v_model",
        "mean_points",
        "quantile_coverage",
        "importance",
    }
    assert expected_keys <= trained.metadata.keys()
    fold_growth = cast(list[object], trained.metadata["fold_growth"])
    assert len(fold_growth) == 4
    assert len(cast(list[str], trained.metadata["feature_columns"])) == 37
    assert trained.metadata["n_snapshots"] == len(pool_df)


def test_quantile_coverage_is_a_fraction(trained: TrainResult) -> None:
    coverage = cast(dict[str, dict[str, float]], trained.metadata["quantile_coverage"])
    for stats in coverage.values():
        assert 0.0 <= stats["p25"] <= 1.0
        assert 0.0 <= stats["p75"] <= 1.0


def test_beats_baselines_has_three_entries(trained: TrainResult) -> None:
    beats = cast(dict[str, bool], trained.metadata["beats_baselines"])
    assert set(beats.keys()) == {"never", "k120_l1", "k120_l5"}


def test_determinism(small_pool: tuple[pd.DataFrame, PriceStore], trained: TrainResult) -> None:
    pool_df, store = small_pool
    result_b = train(pool_df, store.read, _market(store), seed=42, max_iter=MAX_ITER)
    assert trained.metadata["growth_model"] == pytest.approx(result_b.metadata["growth_model"])
    assert trained.metadata["importance"] == pytest.approx(result_b.metadata["importance"])


def test_train_all_accepts_an_all_nan_feature() -> None:
    rng = np.random.default_rng(0)
    x = pd.DataFrame({"a": rng.normal(size=60), "b": np.full(60, np.nan)})
    pool_df = pd.DataFrame(
        {f"v_l{lev}_h{h}": rng.normal(size=60) for lev in LEVELS for h in HORIZONS}
    )
    models = train_all(x, pool_df, seed=1, max_iter=5)
    assert len(models) == len(LEVELS) * len(HORIZONS) * len(QUANTILES)
    assert np.isfinite(models[(1, 10, 0.5)].predict(x)).all()
