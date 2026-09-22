import numpy as np
import pandas as pd
import pytest

from app.indicators import (
    INDICATOR_COLUMNS,
    atr_wilder,
    bollinger,
    rsi_wilder,
    sma,
    with_indicators,
)
from tests.helpers import random_walk_bars

APPROX = pytest.approx


def test_sma_hand_values() -> None:
    close = pd.Series(range(1, 11), dtype="float64")
    result = sma(close, 3)
    expected = [np.nan, np.nan, 2, 3, 4, 5, 6, 7, 8, 9]
    np.testing.assert_allclose(result.to_numpy(), expected, equal_nan=True)

    close60 = pd.Series(range(1, 61), dtype="float64")
    assert sma(close60, 50).iloc[49] == APPROX(25.5)


def test_bollinger_hand_values() -> None:
    """Hand-calculated: std(ddof=0) of [1, 2, 3] = sqrt(2/3)."""
    close = pd.Series([1.0, 2.0, 3.0, 4.0])
    upper, mid, lower = bollinger(close, n=3, k=2.0)
    assert mid.iloc[2] == APPROX(2.0)
    assert upper.iloc[2] == APPROX(3.632993161855452)
    assert lower.iloc[2] == APPROX(0.36700683814454793)


def test_bollinger_constant() -> None:
    close = pd.Series([5.0] * 25)
    with np.errstate(all="raise"):
        upper, mid, lower = bollinger(close)
    assert upper.iloc[19:].eq(5.0).all()
    assert mid.iloc[19:].eq(5.0).all()
    assert lower.iloc[19:].eq(5.0).all()


def test_rsi_hand_values() -> None:
    """Hand-calculated Wilder RSI, exact fractions."""
    closes = [
        100,
        102,
        101,
        103,
        102,
        104,
        103,
        105,
        104,
        106,
        105,
        107,
        106,
        108,
        107,
        110,
        106,
    ]
    close = pd.Series(closes, dtype="float64")
    rsi = rsi_wilder(close)
    assert rsi.iloc[:14].isna().all()
    assert rsi.iloc[14] == APPROX(200 / 3)
    assert rsi.iloc[15] == APPROX(640 / 9)
    assert rsi.iloc[16] == APPROX(41600 / 697)


def test_rsi_only_gains_is_100() -> None:
    close = pd.Series(range(1, 31), dtype="float64")
    rsi = rsi_wilder(close)
    assert rsi.iloc[14:].eq(100.0).all()


def test_rsi_constant_is_50() -> None:
    close = pd.Series([5.0] * 30)
    rsi = rsi_wilder(close)
    assert rsi.iloc[14:].eq(50.0).all()


def test_rsi_range() -> None:
    for seed in range(20):
        bars = random_walk_bars(300, seed)
        rsi = rsi_wilder(bars["close"])
        valid = rsi.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


def test_atr_hand_values() -> None:
    """Hand-calculated Wilder ATR: TR[1..14] = 2 (steady), TR[15] = 8 (gap up), TR[16] = 7."""
    high = [11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18, 25, 19]
    low = [9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 20, 17]
    close = [10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 24, 18]
    atr = atr_wilder(
        pd.Series(high, dtype="float64"),
        pd.Series(low, dtype="float64"),
        pd.Series(close, dtype="float64"),
    )
    assert atr.iloc[14] == APPROX(2.0)
    assert atr.iloc[15] == APPROX(17 / 7)
    assert atr.iloc[16] == APPROX(135 / 49)


def test_causality() -> None:
    rng = np.random.default_rng(0)
    for seed in range(20):
        n = int(rng.integers(300, 700))
        t = int(rng.integers(0, n))
        bars = random_walk_bars(n, seed)
        prefix_first = with_indicators(bars.iloc[: t + 1])
        prefix_second = with_indicators(bars).iloc[: t + 1]
        pd.testing.assert_frame_equal(prefix_first, prefix_second, check_exact=True)


def test_with_indicators_adds_columns() -> None:
    bars = random_walk_bars(300, seed=1)
    result = with_indicators(bars)
    for col in INDICATOR_COLUMNS:
        assert col in result.columns
