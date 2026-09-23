"""Tests for app.ml growth metrics, baselines and fold aggregation (PRD R14 v0.6)."""

import math
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from app.ml import (
    BASELINES,
    FoldResult,
    Recommendation,
    aggregate_folds,
    baseline_booked,
    booked_value,
    growth,
    option_values_at_level,
    realized_value,
    recommendation_points,
)
from app.trading import Level, OptionCode, points


def _row(v1: tuple[float, float, float], v5: tuple[float, float, float]) -> pd.Series:
    data: dict[str, float] = {}
    for level, values in ((1, v1), (5, v5)):
        for horizon, v in zip((10, 30, 120), values, strict=True):
            data[f"v_l{level}_h{horizon}"] = v
    return pd.Series(data)


def test_growth_of_known_values() -> None:
    assert growth(np.array([0.1, -0.05])) == pytest.approx((math.log(1.1) + math.log(0.95)) / 2)
    assert growth(np.array([])) == 0.0


def test_booked_value_wait_is_zero_buy_is_stored_value() -> None:
    row = _row((0.01, 0.02, 0.03), (0.05, 0.10, 0.15))
    assert booked_value(row, Recommendation(OptionCode.W30, Level.EINFACH, 0, 0, 0, 0)) == 0.0
    buy = Recommendation(OptionCode.K30, Level.MITTEL, 0, 0, 0, 0)
    assert booked_value(row, buy) == pytest.approx(0.10)


def test_game_view_is_unchanged() -> None:
    row = _row((0.01, 0.02, 0.05), (0.05, 0.10, 0.15))
    wait = Recommendation(OptionCode.W120, Level.EINFACH, 0, 0, 0, 0)
    assert realized_value(row, wait) == pytest.approx(-0.05)
    buy = Recommendation(OptionCode.K120, Level.EINFACH, 0, 0, 0, 0)
    assert recommendation_points(row, buy) == points(option_values_at_level(row, 1))[buy.option]


def test_baselines() -> None:
    df = pd.DataFrame(
        [_row((0.0, 0.0, 0.03), (0.0, 0.0, 0.15)), _row((0.0, 0.0, -0.01), (0.0, 0.0, -0.05))]
    )
    assert set(BASELINES) == {"never", "k120_l1", "k120_l5"}
    assert baseline_booked(df, BASELINES["never"]).tolist() == [0.0, 0.0]
    assert baseline_booked(df, BASELINES["k120_l1"]).tolist() == pytest.approx([0.03, -0.01])
    assert baseline_booked(df, BASELINES["k120_l5"]).tolist() == pytest.approx([0.15, -0.05])


def _fold(model: list[float], k1: list[float], k5: list[float], traded: list[bool]) -> FoldResult:
    n = len(model)
    return FoldResult(
        models={},
        booked_model=np.array(model),
        booked_baselines={"never": np.zeros(n), "k120_l1": np.array(k1), "k120_l5": np.array(k5)},
        traded=np.array(traded),
        game_v=np.array(model),
        points=np.array([100] * n),
        coverage={(1, 10): (0.2, 0.8)},
    )


def test_aggregate_growth_and_beats() -> None:
    folds = [
        _fold([0.1, 0.0], [0.05, -0.05], [0.2, -0.3], [True, False]),
        _fold([-0.02, 0.04], [0.01, 0.01], [-0.1, 0.1], [True, True]),
    ]
    out = cast(dict[str, Any], aggregate_folds(folds))

    model_all = np.log1p([0.1, 0.0, -0.02, 0.04]).mean()
    k5_all = np.log1p([0.2, -0.3, -0.1, 0.1]).mean()
    assert out["growth_model"] == pytest.approx(model_all)
    assert out["growth_baselines"]["k120_l5"] == pytest.approx(k5_all)
    assert out["beats_baselines"] == {
        "never": model_all > 0,
        "k120_l1": model_all > np.log1p([0.05, -0.05, 0.01, 0.01]).mean(),
        "k120_l5": model_all > k5_all,
    }
    fold2_model = np.log1p([-0.02, 0.04]).mean()
    assert out["fold_growth"][1]["model"] == pytest.approx(fold2_model)
    assert out["worst_fold_growth"]["model"] == pytest.approx(fold2_model)
    assert out["all_folds_positive"] is True
    assert out["traded_share"] == pytest.approx(0.75)
    assert out["booked_p5"] == pytest.approx(np.percentile([0.1, 0.0, -0.02, 0.04], 5))
    assert out["mean_points"] == pytest.approx(100.0)
    assert out["quantile_coverage"]["l1_h10"] == {
        "p25": pytest.approx(0.2),
        "p75": pytest.approx(0.8),
    }


def test_aggregate_negative_fold() -> None:
    folds = [_fold([0.1], [0.0], [0.0], [True]), _fold([-0.1], [0.0], [0.0], [True])]
    assert aggregate_folds(folds)["all_folds_positive"] is False
