# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: scikit-learn ships no type stubs; untyped calls stay inside this module (D14).
"""ML model: quantile regression per (leverage, horizon), recommendation and validation.

PRD R13 (growth rule) and R14 (growth metrics), v0.6. See docs/spec-m7-model.md and
docs/spec-m7-1-improve.md.
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
from app.features import FEATURE_COLUMNS, STOCK_FEATURES, compute_features, with_market
from app.indicators import with_indicators
from app.signals import signal_flags
from app.trading import (
    HORIZONS,
    Level,
    OptionCode,
    buy_option,
    horizon_of,
    is_buy,
    points,
    wait_option,
)

LEVELS = (1, 5)
QUANTILES = (0.25, 0.5, 0.75)
N_FOLDS = 4
LEVEL_OF = {1: Level.EINFACH, 5: Level.MITTEL}
LEVEL_TO_L = {level: leverage for leverage, level in LEVEL_OF.items()}
HYPERPARAMS: dict[str, float] = {
    "learning_rate": 0.05,
    "min_samples_leaf": 200,
    "max_leaf_nodes": 15,
    "l2_regularization": 1.0,
}
DEFAULT_MAX_ITER = 200
LOG_FLOOR = -0.99
BASELINES: dict[str, tuple[int, int] | None] = {
    "never": None,
    "k120_l1": (1, 120),
    "k120_l5": (5, 120),
}

LoadFn = Callable[[str], pd.DataFrame]
_FloatArray = np.ndarray[tuple[int], np.dtype[np.float64]]
_BoolArray = np.ndarray[tuple[int], np.dtype[np.bool_]]
_Quantiles = tuple[float, float, float]


@dataclass(frozen=True)
class Recommendation:
    option: OptionCode
    level: Level
    p25: float
    p50: float
    p75: float
    growth: float


def growth_score(q: _Quantiles) -> float:
    """G = mean of ln(1 + max(q, -0.99)) over the three quantiles (R13)."""
    return float(np.mean(np.log1p(np.maximum(np.array(q, dtype=np.float64), LOG_FLOOR))))


def rank_buys(quantiles: Mapping[tuple[int, int], _Quantiles]) -> list[Recommendation]:
    """All (L, H) buy pairs, largest G first (ties: smaller L, then smaller H)."""
    pairs = [(leverage, horizon) for leverage in LEVELS for horizon in HORIZONS]
    scores = {lh: growth_score(quantiles[lh]) for lh in pairs}
    ranked = sorted(pairs, key=lambda lh: (-scores[lh], lh[0], lh[1]))
    return [
        Recommendation(buy_option(h), LEVEL_OF[lev], *quantiles[(lev, h)], scores[(lev, h)])
        for lev, h in ranked
    ]


def recommend(quantiles: Mapping[tuple[int, int], _Quantiles]) -> Recommendation:
    """R13: the (L, H) with the largest G wins (ties: smaller L, then smaller H); G <= 0 waits."""
    best = rank_buys(quantiles)[0]
    if best.growth > 0:
        return best

    horizon = min(HORIZONS, key=lambda h: (quantiles[(1, h)][1], h))
    q = quantiles[(1, horizon)]
    return Recommendation(wait_option(horizon), Level.EINFACH, -q[2], -q[1], -q[0], growth_score(q))


class QuantileModel(Protocol):
    def predict(self, x: pd.DataFrame, /) -> _FloatArray: ...


def predict_quantiles(
    models: Mapping[tuple[int, int, float], QuantileModel], x: pd.DataFrame
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
    train_mask: _BoolArray
    test_mask: _BoolArray


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


def option_values_at_level(row: pd.Series, level: int) -> dict[OptionCode, float]:
    values: dict[OptionCode, float] = {}
    for horizon in HORIZONS:
        v = float(row[f"v_l{level}_h{horizon}"])
        values[buy_option(horizon)] = v
        values[wait_option(horizon)] = -v
    return values


def realized_value(row: pd.Series, rec: Recommendation) -> float:
    """Game view (R7): W_H is worth -V(K_H)."""
    level_l = LEVEL_TO_L[rec.level]
    v = float(row[f"v_l{level_l}_h{horizon_of(rec.option)}"])
    return v if is_buy(rec.option) else -v


def recommendation_points(row: pd.Series, rec: Recommendation) -> int:
    values = option_values_at_level(row, LEVEL_TO_L[rec.level])
    return points(values)[rec.option]


def booked_value(row: pd.Series, rec: Recommendation) -> float:
    """Money view (R9): only K options book; W books 0."""
    if not is_buy(rec.option):
        return 0.0
    return float(row[f"v_l{LEVEL_TO_L[rec.level]}_h{horizon_of(rec.option)}"])


def growth(booked: _FloatArray) -> float:
    """Mean log growth of the balance per round (R14); 0 for no rounds."""
    return float(np.log1p(booked).mean()) if len(booked) else 0.0


def baseline_booked(df: pd.DataFrame, pair: tuple[int, int] | None) -> _FloatArray:
    if pair is None:
        return np.zeros(len(df), dtype=np.float64)
    return df[f"v_l{pair[0]}_h{pair[1]}"].to_numpy(dtype=np.float64)


def build_feature_frame(pool_df: pd.DataFrame, load: LoadFn, market: pd.DataFrame) -> pd.DataFrame:
    """One row per snapshot, in `pool_df`'s order: snapshot_id, t0, t_end (bar index + FUTURE),
    then FEATURE_COLUMNS. Loads each ticker once; market row = the one at t0."""
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
    stock = pd.DataFrame(rows).set_index("snapshot_id").loc[pool_df["snapshot_id"]].reset_index()
    full = with_market(stock[list(STOCK_FEATURES)], stock["t0"], market)
    return pd.concat([stock[["snapshot_id", "t0", "t_end"]], full], axis=1)


def _make_regressor(quantile: float, seed: int, max_iter: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        random_state=seed,
        max_iter=max_iter,
        learning_rate=HYPERPARAMS["learning_rate"],
        min_samples_leaf=int(HYPERPARAMS["min_samples_leaf"]),
        max_leaf_nodes=int(HYPERPARAMS["max_leaf_nodes"]),
        l2_regularization=HYPERPARAMS["l2_regularization"],
    )


def train_all(
    x: pd.DataFrame, pool_df: pd.DataFrame, seed: int, max_iter: int = DEFAULT_MAX_ITER
) -> dict[tuple[int, int, float], HistGradientBoostingRegressor]:
    """18 models: one per (leverage, horizon, quantile), target `v_l{L}_h{H}`.

    `max_iter` may be lowered in tests to keep the suite fast (docs/spec-m7-model.md §5).
    """
    # sklearn 1.9.1's binning raises on an all-NaN column (e.g. market features with < 30
    # tickers); a constant column carries the same (no) information and fits fine.
    x = x.copy()
    x.loc[:, x.isna().all()] = 0.0
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
class FoldResult:
    models: Mapping[tuple[int, int, float], QuantileModel]
    booked_model: _FloatArray
    booked_baselines: dict[str, _FloatArray]
    traded: _BoolArray
    game_v: _FloatArray
    points: np.ndarray[tuple[int], np.dtype[np.int64]]
    coverage: dict[tuple[int, int], tuple[float, float]]


def _row_quantiles(
    preds: Mapping[tuple[int, int], tuple[_FloatArray, _FloatArray, _FloatArray]], pos: int
) -> dict[tuple[int, int], _Quantiles]:
    return {lh: (float(a[0][pos]), float(a[1][pos]), float(a[2][pos])) for lh, a in preds.items()}


def _evaluate_fold(
    pool_df: pd.DataFrame, x: pd.DataFrame, fold: Fold, seed: int, max_iter: int
) -> FoldResult:
    models = train_all(x[fold.train_mask], pool_df[fold.train_mask], seed, max_iter)
    test_df = pool_df[fold.test_mask]
    preds = predict_quantiles(models, x[fold.test_mask])
    rows = [row for _, row in test_df.iterrows()]
    recs = [recommend(_row_quantiles(preds, pos)) for pos in range(len(rows))]
    pairs = list(zip(rows, recs, strict=True))
    return FoldResult(
        models=models,
        booked_model=np.array([booked_value(r, rec) for r, rec in pairs], dtype=np.float64),
        booked_baselines={name: baseline_booked(test_df, lh) for name, lh in BASELINES.items()},
        traded=np.array([is_buy(rec.option) for rec in recs], dtype=bool),
        game_v=np.array([realized_value(r, rec) for r, rec in pairs], dtype=np.float64),
        points=np.array([recommendation_points(r, rec) for r, rec in pairs], dtype=np.int64),
        coverage={
            lh: _coverage_for_pair(test_df[f"v_l{lh[0]}_h{lh[1]}"], p[0], p[2])
            for lh, p in preds.items()
        },
    )


def _growth_summary(results: Sequence[FoldResult]) -> dict[str, object]:
    names = list(BASELINES)
    model_all = np.concatenate([r.booked_model for r in results])
    g_model = growth(model_all)
    g_base = {n: growth(np.concatenate([r.booked_baselines[n] for r in results])) for n in names}
    fold_growth = [
        {"model": growth(r.booked_model), **{n: growth(r.booked_baselines[n]) for n in names}}
        for r in results
    ]
    return {
        "growth_model": g_model,
        "growth_baselines": g_base,
        "beats_baselines": {n: g_model > g for n, g in g_base.items()},
        "fold_growth": fold_growth,
        "worst_fold_growth": {k: min(f[k] for f in fold_growth) for k in ["model", *names]},
        "all_folds_positive": all(f["model"] > 0 for f in fold_growth),
        "traded_share": float(np.concatenate([r.traded for r in results]).mean()),
        "booked_p5": float(np.percentile(model_all, 5)),
    }


def _secondary_summary(results: Sequence[FoldResult]) -> dict[str, object]:
    coverage = {
        f"l{lh[0]}_h{lh[1]}": {
            "p25": float(np.mean([r.coverage[lh][0] for r in results])),
            "p75": float(np.mean([r.coverage[lh][1] for r in results])),
        }
        for lh in results[0].coverage
    }
    return {
        "mean_v_model": float(np.concatenate([r.game_v for r in results]).mean()),
        "mean_points": float(np.concatenate([r.points for r in results]).mean()),
        "quantile_coverage": coverage,
    }


def aggregate_folds(results: Sequence[FoldResult]) -> dict[str, object]:
    """R14 v0.6 report: growth vs. baselines (A25), fold stability, game view, coverage."""
    return {**_growth_summary(results), **_secondary_summary(results)}


def _importance_report(
    models: Mapping[tuple[int, int, float], QuantileModel],
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


def _run_metadata(
    pool_df: pd.DataFrame, t0: pd.Series, seed: int, max_iter: int
) -> dict[str, object]:
    return {
        "feature_columns": list(FEATURE_COLUMNS),
        "seed": seed,
        "levels": list(LEVELS),
        "horizons": list(HORIZONS),
        "quantiles": list(QUANTILES),
        "hyperparameters": {**HYPERPARAMS, "max_iter": max_iter},
        "n_snapshots": len(pool_df),
        "data_as_of": t0.max().strftime("%Y-%m-%d"),
        "period": [t0.min().strftime("%Y-%m-%d"), t0.max().strftime("%Y-%m-%d")],
    }


def train(
    pool_df: pd.DataFrame,
    load: LoadFn,
    market: pd.DataFrame,
    seed: int,
    max_iter: int = DEFAULT_MAX_ITER,
) -> TrainResult:
    """R14 end to end: build features, walk-forward validate, then fit on all data (R13's models).

    `max_iter` may be lowered in tests to keep the suite fast (docs/spec-m7-model.md §5).
    """
    pool_df = pool_df.reset_index(drop=True)
    features = build_feature_frame(pool_df, load, market)
    x = features[list(FEATURE_COLUMNS)]

    folds = time_folds(features["t0"], features["t_end"])
    results = [_evaluate_fold(pool_df, x, fold, seed, max_iter) for fold in folds]
    metadata = aggregate_folds(results)
    last = folds[-1]
    metadata["importance"] = _importance_report(
        results[-1].models, x[last.test_mask], pool_df[last.test_mask], seed
    )
    metadata.update(_run_metadata(pool_df, features["t0"], seed, max_iter))
    models = train_all(x, pool_df, seed, max_iter)
    return TrainResult(features=features, models=models, metadata=metadata)
