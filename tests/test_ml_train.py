"""End-to-end test for app.ml.train (PRD R14)."""

from typing import cast

import pandas as pd
import pytest

from app.ml import HORIZONS, LEVELS, QUANTILES, TrainResult, train
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
    return train(pool_df, store.read, seed=42, max_iter=MAX_ITER)


def test_train_produces_27_models(trained: TrainResult) -> None:
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
        "fold_metrics",
        "mean_v_model",
        "mean_v_baselines",
        "beats_baselines",
        "mean_points",
        "quantile_coverage",
        "importance",
    }
    assert expected_keys <= trained.metadata.keys()
    fold_metrics = cast(list[object], trained.metadata["fold_metrics"])
    assert len(fold_metrics) == 4
    assert trained.metadata["n_snapshots"] == len(pool_df)


def test_quantile_coverage_is_a_fraction(trained: TrainResult) -> None:
    coverage = cast(dict[str, dict[str, float]], trained.metadata["quantile_coverage"])
    for stats in coverage.values():
        assert 0.0 <= stats["p25"] <= 1.0
        assert 0.0 <= stats["p75"] <= 1.0


def test_beats_baselines_has_three_entries(trained: TrainResult) -> None:
    beats = cast(dict[str, bool], trained.metadata["beats_baselines"])
    assert set(beats.keys()) == {"always_k120", "most_frequent_label", "random"}


def test_determinism(small_pool: tuple[pd.DataFrame, PriceStore], trained: TrainResult) -> None:
    pool_df, store = small_pool
    result_b = train(pool_df, store.read, seed=42, max_iter=MAX_ITER)
    assert trained.metadata["mean_v_model"] == pytest.approx(result_b.metadata["mean_v_model"])
    assert trained.metadata["importance"] == pytest.approx(result_b.metadata["importance"])
