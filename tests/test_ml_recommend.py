"""Tests for app.ml.recommend and predict_quantiles (PRD R13)."""

from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest

from app.ml import predict_quantiles, recommend
from app.trading import Level, OptionCode


def _quantiles(
    overrides: Mapping[tuple[int, int], tuple[float, float, float]],
) -> dict[tuple[int, int], tuple[float, float, float]]:
    base = {(lev, h): (-0.05, 0.0, 0.05) for lev in (1, 5, 10) for h in (10, 30, 120)}
    base.update(overrides)
    return base


def test_k_wins_with_positive_p25() -> None:
    q = _quantiles({(5, 30): (0.01, 0.05, 0.10)})
    rec = recommend(q)
    assert rec.option == OptionCode.K30
    assert rec.level == Level.MITTEL
    assert rec.p25 == pytest.approx(0.01)
    assert rec.p50 == pytest.approx(0.05)
    assert rec.p75 == pytest.approx(0.10)


def test_tie_break_prefers_smaller_leverage() -> None:
    q = _quantiles({(5, 30): (0.02, 0.05, 0.10), (10, 30): (0.02, 0.06, 0.11)})
    rec = recommend(q)
    assert rec.level == Level.MITTEL
    assert rec.option == OptionCode.K30


def test_tie_break_prefers_smaller_horizon_after_leverage() -> None:
    q = _quantiles({(1, 10): (0.02, 0.03, 0.04), (1, 30): (0.02, 0.05, 0.10)})
    rec = recommend(q)
    assert rec.level == Level.EINFACH
    assert rec.option == OptionCode.K10


def test_wait_when_all_p25_non_positive() -> None:
    q = _quantiles(
        {
            (1, 10): (-0.01, 0.02, 0.05),
            (1, 30): (-0.02, -0.01, 0.03),
            (1, 120): (-0.03, 0.04, 0.09),
        }
    )
    rec = recommend(q)
    assert rec.option == OptionCode.W30
    assert rec.level == Level.EINFACH
    assert rec.p25 == pytest.approx(-0.03)
    assert rec.p50 == pytest.approx(0.01)
    assert rec.p75 == pytest.approx(0.02)


def test_wait_tie_break_prefers_smaller_horizon() -> None:
    q = _quantiles({(1, 10): (-0.01, 0.0, 0.01), (1, 30): (-0.02, 0.0, 0.02)})
    rec = recommend(q)
    assert rec.option == OptionCode.W10


def test_p25_exactly_zero_is_not_positive() -> None:
    q = _quantiles({(1, 10): (0.0, 0.0, 0.0)})
    rec = recommend(q)
    assert rec.option.value.startswith("W")


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
