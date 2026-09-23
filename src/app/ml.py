# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: scikit-learn ships no type stubs; untyped calls stay inside this module (D14).
"""ML model: quantile regression per (leverage, horizon), recommendation and validation.

PRD R13 (recommendation) and R14 (validation). See docs/spec-m7-model.md.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import make_scorer, mean_pinball_loss

from app.eligibility import FUTURE
from app.features import FEATURE_COLUMNS, compute_features
from app.indicators import with_indicators
from app.signals import signal_flags
from app.trading import (
    HORIZONS,
    OPTIONS,
    Level,
    OptionCode,
    buy_option,
    horizon_of,
    is_buy,
    points,
    wait_option,
)

LEVELS = (1, 5, 10)
QUANTILES = (0.25, 0.5, 0.75)
N_FOLDS = 4
LEVEL_OF = {1: Level.EINFACH, 5: Level.MITTEL, 10: Level.PROFI}
LEVEL_TO_L = {level: leverage for leverage, level in LEVEL_OF.items()}

LoadFn = Callable[[str], pd.DataFrame]
_FloatArray = np.ndarray[tuple[int], np.dtype[np.float64]]


@dataclass(frozen=True)
class Recommendation:
    option: OptionCode
    level: Level
    p25: float
    p50: float
    p75: float


def recommend(quantiles: Mapping[tuple[int, int], tuple[float, float, float]]) -> Recommendation:
    """R13: the (L, H) with the largest P25 wins (ties: smaller L, then smaller H)."""
    pairs = [(leverage, horizon) for leverage in LEVELS for horizon in HORIZONS]
    best = min(pairs, key=lambda lh: (-quantiles[lh][0], lh[0], lh[1]))
    p25, p50, p75 = quantiles[best]
    if p25 > 0:
        return Recommendation(buy_option(best[1]), LEVEL_OF[best[0]], p25, p50, p75)

    horizon = min(HORIZONS, key=lambda h: (quantiles[(1, h)][1], h))
    p25_1, p50_1, p75_1 = quantiles[(1, horizon)]
    return Recommendation(wait_option(horizon), Level.EINFACH, -p75_1, -p50_1, -p25_1)


class _QuantileModel(Protocol):
    def predict(self, x: pd.DataFrame, /) -> _FloatArray: ...


def predict_quantiles(
    models: Mapping[tuple[int, int, float], _QuantileModel], x: pd.DataFrame
) -> dict[tuple[int, int], tuple[_FloatArray, _FloatArray, _FloatArray]]:
    """Per (L, H): the three quantile models' predictions, sorted per row (no crossing)."""
    out: dict[tuple[int, int], tuple[_FloatArray, _FloatArray, _FloatArray]] = {}
    for leverage in LEVELS:
        for horizon in HORIZONS:
            stacked = np.column_stack(
                [models[(leverage, horizon, q)].predict(x) for q in QUANTILES]
            )
            stacked.sort(axis=1)
            out[(leverage, horizon)] = (stacked[:, 0], stacked[:, 1], stacked[:, 2])
    return out


@dataclass(frozen=True)
class Fold:
    train_mask: np.ndarray[tuple[int], np.dtype[np.bool_]]
    test_mask: np.ndarray[tuple[int], np.dtype[np.bool_]]


def time_folds(t0: pd.Series, t_end: pd.Series, n_folds: int = N_FOLDS) -> list[Fold]:
    """R14: newer 50% of rows (by t0), split into `n_folds` contiguous test blocks; a fold trains
    on every row whose t_end is before its block's earliest t0 (embargo)."""
    order = t0.sort_values(kind="stable").index.to_numpy()
    newer_half = order[len(order) // 2 :]
    blocks = np.array_split(newer_half, n_folds)

    folds: list[Fold] = []
    for block in blocks:
        min_t0 = t0.loc[block].min()
        train_mask = (t_end < min_t0).to_numpy()
        test_mask = np.zeros(len(t0), dtype=bool)
        test_mask[block] = True
        folds.append(Fold(train_mask, test_mask))
    return folds


def option_value_l1(row: pd.Series, option: OptionCode) -> float:
    v = float(row[f"v_l1_h{horizon_of(option)}"])
    return v if is_buy(option) else -v


def option_values_at_level(row: pd.Series, level: int) -> dict[OptionCode, float]:
    values: dict[OptionCode, float] = {}
    for horizon in HORIZONS:
        v = float(row[f"v_l{level}_h{horizon}"])
        values[buy_option(horizon)] = v
        values[wait_option(horizon)] = -v
    return values


def realized_value(row: pd.Series, rec: Recommendation) -> float:
    level_l = LEVEL_TO_L[rec.level]
    v = float(row[f"v_l{level_l}_h{horizon_of(rec.option)}"])
    return v if is_buy(rec.option) else -v


def recommendation_points(row: pd.Series, rec: Recommendation) -> int:
    values = option_values_at_level(row, LEVEL_TO_L[rec.level])
    return points(values)[rec.option]


def baseline_always_k120(
    df: pd.DataFrame, mask: np.ndarray[tuple[int], np.dtype[np.bool_]]
) -> float:
    return float(df.loc[mask, "v_l1_h120"].mean())


def baseline_most_frequent_label(train_df: pd.DataFrame, test_df: pd.DataFrame) -> float:
    labels = train_df.loc[train_df["label_l1"] != "NEUTRAL", "label_l1"]
    if labels.empty:
        return 0.0
    option = OptionCode(str(labels.value_counts().idxmax()))
    values = [option_value_l1(row, option) for _, row in test_df.iterrows()]
    return float(np.mean(values)) if values else 0.0


def baseline_random(
    df: pd.DataFrame, mask: np.ndarray[tuple[int], np.dtype[np.bool_]], seed: int
) -> float:
    rows = df.loc[mask]
    rng = np.random.default_rng(seed)
    choices = rng.integers(0, len(OPTIONS), size=len(rows))
    values = [
        option_value_l1(row, OPTIONS[int(c)])
        for (_, row), c in zip(rows.iterrows(), choices, strict=True)
    ]
    return float(np.mean(values)) if values else 0.0


def build_feature_frame(pool_df: pd.DataFrame, load: LoadFn) -> pd.DataFrame:
    """One row per snapshot: snapshot_id, t0, t_end (t0's bar index + FUTURE), 29 features.
    Loads each ticker once; rows come back in `pool_df`'s order."""
    rows: list[dict[str, object]] = []
    for ticker, group in pool_df.groupby("ticker"):
        bars = load(str(ticker))
        ind = with_indicators(bars)
        feats = compute_features(ind, signal_flags(ind))
        for _, snap in group.iterrows():
            i = int(snap["n_hist"]) - 1
            row: dict[str, object] = {
                "snapshot_id": snap["snapshot_id"],
                "t0": snap["t0"],
                "t_end": pd.Timestamp(bars["date"].iloc[i + FUTURE]),
            }
            row.update({str(key): value for key, value in feats.iloc[i].items()})
            rows.append(row)
    result = pd.DataFrame(rows).set_index("snapshot_id")
    return result.loc[pool_df["snapshot_id"]].reset_index()


DEFAULT_MAX_ITER = 100


def _make_regressor(quantile: float, seed: int, max_iter: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, random_state=seed, max_iter=max_iter
    )


def train_all(
    x: pd.DataFrame, pool_df: pd.DataFrame, seed: int, max_iter: int = DEFAULT_MAX_ITER
) -> dict[tuple[int, int, float], HistGradientBoostingRegressor]:
    """27 models: one per (leverage, horizon, quantile), target `v_l{L}_h{H}`.

    `max_iter` may be lowered in tests to keep the suite fast (docs/spec-m7-model.md §5).
    """
    models: dict[tuple[int, int, float], HistGradientBoostingRegressor] = {}
    for leverage in LEVELS:
        for horizon in HORIZONS:
            y = pool_df[f"v_l{leverage}_h{horizon}"]
            for q in QUANTILES:
                model = _make_regressor(q, seed, max_iter)
                model.fit(x, y)
                models[(leverage, horizon, q)] = model
    return models


def _coverage_for_pair(
    y_true: pd.Series, p25: _FloatArray, p75: _FloatArray
) -> tuple[float, float]:
    y = y_true.to_numpy()
    return float(np.mean(y <= p25)), float(np.mean(y <= p75))


@dataclass(frozen=True)
class _FoldResult:
    models: dict[tuple[int, int, float], HistGradientBoostingRegressor]
    mean_v_model: float
    mean_v_baselines: dict[str, float]
    mean_points: float
    coverage: dict[tuple[int, int], tuple[float, float]]
    n_test: int


def _evaluate_fold(
    pool_df: pd.DataFrame, x: pd.DataFrame, fold: Fold, seed: int, max_iter: int
) -> _FoldResult:
    models = train_all(x[fold.train_mask], pool_df[fold.train_mask], seed, max_iter)
    x_test = x[fold.test_mask]
    test_df = pool_df[fold.test_mask]
    quantile_preds = predict_quantiles(models, x_test)

    values: list[float] = []
    point_values: list[int] = []
    for pos, (_, row) in enumerate(test_df.iterrows()):
        row_quantiles = {
            lh: (float(arr[0][pos]), float(arr[1][pos]), float(arr[2][pos]))
            for lh, arr in quantile_preds.items()
        }
        rec = recommend(row_quantiles)
        values.append(realized_value(row, rec))
        point_values.append(recommendation_points(row, rec))

    coverage = {
        lh: _coverage_for_pair(test_df[f"v_l{lh[0]}_h{lh[1]}"], p25, p75)
        for lh, (p25, _p50, p75) in quantile_preds.items()
    }
    baselines = {
        "always_k120": baseline_always_k120(pool_df, fold.test_mask),
        "most_frequent_label": baseline_most_frequent_label(
            pool_df[fold.train_mask], pool_df[fold.test_mask]
        ),
        "random": baseline_random(pool_df, fold.test_mask, seed),
    }
    return _FoldResult(
        models=models,
        mean_v_model=float(np.mean(values)),
        mean_v_baselines=baselines,
        mean_points=float(np.mean(point_values)),
        coverage=coverage,
        n_test=len(values),
    )


def _weighted_mean(values: Sequence[float], weights: Sequence[int]) -> float:
    total = sum(weights)
    return sum(v * w for v, w in zip(values, weights, strict=True)) / total


def _aggregate_folds(fold_results: Sequence[_FoldResult]) -> dict[str, object]:
    weights = [fr.n_test for fr in fold_results]
    mean_v_model = _weighted_mean([fr.mean_v_model for fr in fold_results], weights)
    mean_points = _weighted_mean([fr.mean_points for fr in fold_results], weights)
    baseline_names = fold_results[0].mean_v_baselines.keys()
    mean_v_baselines = {
        name: _weighted_mean([fr.mean_v_baselines[name] for fr in fold_results], weights)
        for name in baseline_names
    }
    coverage = {
        f"l{leverage}_h{horizon}": {
            "p25": float(np.mean([fr.coverage[(leverage, horizon)][0] for fr in fold_results])),
            "p75": float(np.mean([fr.coverage[(leverage, horizon)][1] for fr in fold_results])),
        }
        for leverage in LEVELS
        for horizon in HORIZONS
    }
    beats_baselines = {name: mean_v_model > value for name, value in mean_v_baselines.items()}
    fold_metrics = [
        {
            "n_test": fr.n_test,
            "mean_v_model": fr.mean_v_model,
            "mean_v_baselines": fr.mean_v_baselines,
            "mean_points": fr.mean_points,
        }
        for fr in fold_results
    ]
    return {
        "mean_v_model": mean_v_model,
        "mean_v_baselines": mean_v_baselines,
        "beats_baselines": beats_baselines,
        "mean_points": mean_points,
        "quantile_coverage": coverage,
        "fold_metrics": fold_metrics,
    }


def _importance_report(
    models: Mapping[tuple[int, int, float], HistGradientBoostingRegressor],
    x_test: pd.DataFrame,
    test_df: pd.DataFrame,
    seed: int,
) -> dict[str, float]:
    """Permutation importance of the P50/L=1 models, averaged over the three horizons (R14)."""
    scorer = make_scorer(mean_pinball_loss, alpha=0.5, greater_is_better=False)
    totals = np.zeros(len(FEATURE_COLUMNS))
    for horizon in HORIZONS:
        model = models[(1, horizon, 0.5)]
        y = test_df[f"v_l1_h{horizon}"]
        result = cast(
            Any,
            permutation_importance(
                model, x_test, y, scoring=scorer, n_repeats=5, random_state=seed
            ),
        )
        totals += result.importances_mean
    averaged: list[float] = (totals / len(HORIZONS)).tolist()
    ranked = sorted(zip(FEATURE_COLUMNS, averaged, strict=True), key=lambda kv: -kv[1])
    return dict(ranked)


@dataclass(frozen=True)
class TrainResult:
    features: pd.DataFrame
    models: dict[tuple[int, int, float], HistGradientBoostingRegressor]
    metadata: dict[str, object]


def train(
    pool_df: pd.DataFrame, load: LoadFn, seed: int, max_iter: int = DEFAULT_MAX_ITER
) -> TrainResult:
    """R14 end to end: build features, walk-forward validate, then fit on all data (R13's models).

    `max_iter` may be lowered in tests to keep the suite fast (docs/spec-m7-model.md §5).
    """
    pool_df = pool_df.reset_index(drop=True)
    features = build_feature_frame(pool_df, load)
    x = features[list(FEATURE_COLUMNS)]

    folds = time_folds(features["t0"], features["t_end"])
    fold_results = [_evaluate_fold(pool_df, x, fold, seed, max_iter) for fold in folds]
    metadata = _aggregate_folds(fold_results)

    last_fold = folds[-1]
    importance = _importance_report(
        fold_results[-1].models, x[last_fold.test_mask], pool_df[last_fold.test_mask], seed
    )

    models = train_all(x, pool_df, seed, max_iter)
    metadata.update(
        {
            "feature_columns": list(FEATURE_COLUMNS),
            "seed": seed,
            "levels": list(LEVELS),
            "horizons": list(HORIZONS),
            "quantiles": list(QUANTILES),
            "n_snapshots": len(pool_df),
            "data_as_of": features["t0"].max().strftime("%Y-%m-%d"),
            "period": [
                features["t0"].min().strftime("%Y-%m-%d"),
                features["t0"].max().strftime("%Y-%m-%d"),
            ],
            "importance": importance,
        }
    )
    return TrainResult(features=features, models=models, metadata=metadata)
