import numpy as np
import pandas as pd
import pytest

from app.indicators import with_indicators
from app.signals import EVENTS, signal_flags
from tests.helpers import random_walk_bars


def _frame(n: int, **cols: pd.Series) -> pd.DataFrame:
    base = {
        "close": pd.Series([50.0] * n),
        "sma50": pd.Series([90.0] * n),
        "sma200": pd.Series([100.0] * n),
        "rsi14": pd.Series([50.0] * n),
        "bb_upper": pd.Series([100.0] * n),
        "bb_lower": pd.Series([0.0] * n),
        "volume": pd.Series([1000.0] * n),
    }
    base.update(cols)
    return pd.DataFrame(base)


def test_golden_cross_window() -> None:
    n = 10
    sma50 = pd.Series([90.0] * 5 + [110.0] * 5)
    flags = signal_flags(_frame(n, sma50=sma50))
    assert flags["sig_GOLDEN_CROSS"].iloc[4] is np.False_ or not flags["sig_GOLDEN_CROSS"].iloc[4]
    assert bool(flags["sig_GOLDEN_CROSS"].iloc[5])
    assert bool(flags["sig_GOLDEN_CROSS"].iloc[6])
    assert bool(flags["sig_GOLDEN_CROSS"].iloc[7])
    assert not flags["sig_GOLDEN_CROSS"].iloc[8]


def test_death_cross_window() -> None:
    n = 10
    sma50 = pd.Series([110.0] * 5 + [90.0] * 5)
    flags = signal_flags(_frame(n, sma50=sma50))
    assert not flags["sig_DEATH_CROSS"].iloc[4]
    assert bool(flags["sig_DEATH_CROSS"].iloc[5])
    assert bool(flags["sig_DEATH_CROSS"].iloc[6])
    assert bool(flags["sig_DEATH_CROSS"].iloc[7])
    assert not flags["sig_DEATH_CROSS"].iloc[8]


def test_sma200_up_window() -> None:
    n = 10
    close = pd.Series([50.0] * 5 + [150.0] * 5)
    flags = signal_flags(_frame(n, close=close))
    assert not flags["sig_SMA200_UP"].iloc[4]
    assert bool(flags["sig_SMA200_UP"].iloc[5])
    assert bool(flags["sig_SMA200_UP"].iloc[7])
    assert not flags["sig_SMA200_UP"].iloc[8]


def test_sma200_down_window() -> None:
    n = 10
    close = pd.Series([150.0] * 5 + [50.0] * 5)
    flags = signal_flags(_frame(n, close=close))
    assert not flags["sig_SMA200_DOWN"].iloc[4]
    assert bool(flags["sig_SMA200_DOWN"].iloc[5])
    assert bool(flags["sig_SMA200_DOWN"].iloc[7])
    assert not flags["sig_SMA200_DOWN"].iloc[8]


def test_rsi_states() -> None:
    n = 3
    rsi = pd.Series([50.0, 20.0, 80.0])
    flags = signal_flags(_frame(n, rsi14=rsi))
    assert flags["sig_RSI_LT_30"].tolist() == [False, True, False]
    assert flags["sig_RSI_GT_70"].tolist() == [False, False, True]


def test_bollinger_states() -> None:
    n = 3
    close = pd.Series([50.0, 150.0, -50.0])
    flags = signal_flags(_frame(n, close=close))
    assert flags["sig_CLOSE_GT_UPPER_BB"].tolist() == [False, True, False]
    assert flags["sig_CLOSE_LT_LOWER_BB"].tolist() == [False, False, True]


def test_volume_spike_uses_prior_baseline() -> None:
    n = 21
    volume_hit = pd.Series([100.0] * 20 + [201.0])
    flags = signal_flags(_frame(n, volume=volume_hit))
    assert bool(flags["sig_VOLUME_SPIKE"].iloc[20])

    volume_miss = pd.Series([100.0] * 20 + [200.0])
    flags_miss = signal_flags(_frame(n, volume=volume_miss))
    assert not flags_miss["sig_VOLUME_SPIKE"].iloc[20]


def test_nan_gives_no_cross_flags() -> None:
    bars = random_walk_bars(210, seed=1)
    ind = with_indicators(bars)
    flags = signal_flags(ind)
    assert not flags["sig_GOLDEN_CROSS"].iloc[:200].any()
    assert not flags["sig_DEATH_CROSS"].iloc[:200].any()
    assert not flags["sig_SMA200_UP"].iloc[:200].any()
    assert not flags["sig_SMA200_DOWN"].iloc[:200].any()


def test_is_signal_day_is_any() -> None:
    rsi = pd.Series([50.0, 20.0, 50.0, 50.0, 50.0])
    flags = signal_flags(_frame(5, rsi14=rsi))
    assert flags["is_signal_day"].tolist() == [False, True, False, False, False]


@pytest.mark.parametrize("seed", range(10))
def test_causality(seed: int) -> None:
    rng = np.random.default_rng(seed)
    bars = random_walk_bars(400, seed=seed)
    ind_full = with_indicators(bars)
    flags_full = signal_flags(ind_full)
    t = int(rng.integers(200, 399))
    ind_prefix = with_indicators(bars.iloc[: t + 1])
    flags_prefix = signal_flags(ind_prefix)
    for event in (*EVENTS, "is_signal_day"):
        column = event if event == "is_signal_day" else f"sig_{event}"
        assert bool(flags_prefix[column].iloc[t]) == bool(flags_full[column].iloc[t])
