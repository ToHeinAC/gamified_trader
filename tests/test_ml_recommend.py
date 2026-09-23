"""Tests for app.ml.recommend and predict_quantiles (PRD R13 v0.6)."""

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest

from app.ml import LEVELS, growth_score, predict_quantiles, rank_buys, recommend
from app.trading import Level, OptionCode

NEG = (-0.05, 0.0, 0.03)  # G < 0: mean(ln 0.95, 0, ln 1.03)


def _quantiles(
    overrides: Mapping[tuple[int, int], tuple[float, float, float]],
) -> dict[tuple[int, int], tuple[float, float, float]]:
    base = {(lev, h): NEG for lev in (1, 5) for h in (10, 30, 120)}
    base.update(overrides)
    return base


def test_growth_score_formula_and_floor() -> None:
    assert growth_score((0.0, 0.02, 0.05)) == pytest.approx(
        (math.log(1.0) + math.log(1.02) + math.log(1.05)) / 3
    )
    assert growth_score((-1.5, 0.0, 0.0)) == pytest.approx(math.log(0.01) / 3)


def test_buy_when_growth_positive() -> None:
    q = _quantiles({(5, 30): (0.0, 0.02, 0.05)})
    rec = recommend(q)
    assert rec.option == OptionCode.K30
    assert rec.level == Level.MITTEL
    assert (rec.p25, rec.p50, rec.p75) == pytest.approx((0.0, 0.02, 0.05))
    assert rec.growth == pytest.approx(growth_score((0.0, 0.02, 0.05)))


def test_buy_even_if_p25_negative() -> None:
    q = _quantiles({(1, 120): (-0.01, 0.02, 0.04)})
    rec = recommend(q)
    assert rec.option == OptionCode.K120
    assert rec.level == Level.EINFACH


def test_tie_break_prefers_smaller_leverage() -> None:
    q = _quantiles({(1, 120): (0.01, 0.02, 0.03), (5, 120): (0.01, 0.02, 0.03)})
    rec = recommend(q)
    assert rec.level == Level.EINFACH
    assert rec.option == OptionCode.K120


def test_tie_break_prefers_smaller_horizon() -> None:
    q = _quantiles({(1, 10): (0.01, 0.02, 0.03), (1, 30): (0.01, 0.02, 0.03)})
    assert recommend(q).option == OptionCode.K10


def test_wait_when_no_positive_growth() -> None:
    q = _quantiles(
        {
            (1, 10): (-0.01, 0.02, 0.05),
            (1, 30): (-0.02, -0.01, 0.01),
            (1, 120): (-0.10, 0.04, 0.05),
        }
    )
    assert growth_score((-0.01, 0.02, 0.05)) > 0  # sanity: (1, 10) would buy ...
    q[(1, 10)] = (-0.06, 0.02, 0.03)  # ... so make it negative too
    rec = recommend(q)
    assert rec.option == OptionCode.W30
    assert rec.level == Level.EINFACH
    assert (rec.p25, rec.p50, rec.p75) == pytest.approx((-0.01, 0.01, 0.02))
    assert rec.growth == pytest.approx(growth_score((-0.02, -0.01, 0.01)))


def test_growth_exactly_zero_waits() -> None:
    q = _quantiles({(1, 10): (0.0, 0.0, 0.0)})
    assert recommend(q).option.value.startswith("W")


def test_only_levels_one_and_five() -> None:
    assert LEVELS == (1, 5)


class _FakeModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x: pd.DataFrame) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
        return np.full(len(x), self.value, dtype=np.float64)


def test_predict_quantiles_sorts_crossed_predictions() -> None:
    models = {}
    for leverage in (1, 5, 10):
        for horizon in (10, 30, 120):
            # deliberately crossed: p25 model predicts a higher value than p75 model
            models[(leverage, horizon, 0.25)] = _FakeModel(0.5)
            models[(leverage, horizon, 0.5)] = _FakeModel(0.3)
            models[(leverage, horizon, 0.75)] = _FakeModel(0.1)
    x = pd.DataFrame({"f": [0, 1, 2]})
    out = predict_quantiles(models, x)
    p25, p50, p75 = out[(5, 30)]
    assert (p25 <= p50).all()
    assert (p50 <= p75).all()
    assert p25.tolist() == [0.1, 0.1, 0.1]
    assert p75.tolist() == [0.5, 0.5, 0.5]


def test_rank_buys_orders_by_growth_with_tie_break() -> None:
    q = _quantiles(
        {
            (5, 30): (0.0, 0.02, 0.05),
            (1, 120): (0.01, 0.02, 0.03),
            (5, 120): (0.01, 0.02, 0.03),
        }
    )
    ranked = rank_buys(q)
    assert len(ranked) == 6
    assert [(r.option, r.level) for r in ranked[:3]] == [
        (OptionCode.K30, Level.MITTEL),
        (OptionCode.K120, Level.EINFACH),
        (OptionCode.K120, Level.MITTEL),
    ]
    assert ranked[0].growth == pytest.approx(growth_score((0.0, 0.02, 0.05)))
    assert (ranked[0].p25, ranked[0].p50, ranked[0].p75) == pytest.approx((0.0, 0.02, 0.05))
