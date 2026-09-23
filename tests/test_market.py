"""Tests for app.market (PRD R12 market part)."""

import numpy as np
import pandas as pd
import pytest

from app.market import MARKET_COLUMNS, market_frame, market_return
from tests.helpers import make_bars, random_walk_bars


def _frame(frames: dict[str, pd.DataFrame], min_tickers: int) -> pd.DataFrame:
    return market_frame(sorted(frames), frames.__getitem__, min_tickers=min_tickers)


def test_columns_and_index() -> None:
    frames = {"A": random_walk_bars(30, seed=1), "B": random_walk_bars(30, seed=2)}
    mkt = _frame(frames, 2)
    assert tuple(mkt.columns) == MARKET_COLUMNS
    assert mkt.index.name == "date"
    assert mkt.index.is_monotonic_increasing


def test_market_return_by_hand() -> None:
    # A rises 1 % per bar, B is flat: m_t = 0.5 % from the second bar on.
    frames = {
        "A": make_bars([100.0 * 1.01**i for i in range(25)]),
        "B": make_bars([50.0] * 25),
    }
    mkt = _frame(frames, 2)
    assert mkt.iloc[0].isna().all()  # first date has no returns -> row is empty
    assert pd.isna(mkt["mkt_ret_20"].iloc[19])
    assert mkt["mkt_ret_20"].iloc[20] == pytest.approx(1.005**20 - 1, abs=1e-12)
    assert mkt["mkt_ret_20"].iloc[24] == pytest.approx(1.005**20 - 1, abs=1e-12)


def test_breadth_by_hand() -> None:
    frames = {
        "UP": make_bars([10.0 + 0.1 * i for i in range(210)]),
        "DOWN": make_bars([50.0 - 0.1 * i for i in range(210)]),
    }
    mkt = _frame(frames, 2)
    assert pd.isna(mkt["mkt_breadth200"].iloc[198])  # no SMA200 yet
    assert mkt["mkt_breadth200"].iloc[209] == pytest.approx(0.5)


def test_too_few_returns_empties_the_row() -> None:
    a = make_bars([100.0, 101.0, 102.0, 103.0])
    b = make_bars([50.0, 51.0, 52.0, 53.0]).drop(index=2).reset_index(drop=True)
    mkt = _frame({"A": a, "B": b}, 2)
    missing_day = a["date"].iloc[2]
    assert mkt.loc[missing_day].isna().all()


def test_glitch_return_is_ignored() -> None:
    frames = {
        "A": make_bars([100.0, 180.0]),  # +80 % -> data error
        "B": make_bars([100.0, 101.0]),
        "C": make_bars([100.0, 103.0]),
    }
    day = frames["A"]["date"].iloc[1]
    m = market_return(sorted(frames), frames.__getitem__, 2)
    assert m.loc[day] == pytest.approx(0.02)  # mean(+1 %, +3 %); A's +80 % is ignored


def test_returns_use_each_tickers_own_calendar() -> None:
    a = make_bars([100.0, 110.0, 121.0])
    b = make_bars([100.0, 100.0, 120.0]).drop(index=1).reset_index(drop=True)
    m = market_return(["A", "B"], {"A": a, "B": b}.__getitem__, 1)
    day1, day2 = a["date"].iloc[1], a["date"].iloc[2]
    assert m.loc[day1] == pytest.approx(0.10)  # only A has a bar that day
    assert m.loc[day2] == pytest.approx((0.10 + 0.20) / 2)  # B: 120 / 100 over its own bars


@pytest.mark.parametrize("seed", range(5))
def test_causality(seed: int) -> None:
    frames = {t: random_walk_bars(320, seed=seed * 10 + i) for i, t in enumerate("ABC")}
    full = _frame(frames, 2)
    t = int(np.random.default_rng(seed).integers(260, 319))
    cut_date = frames["A"]["date"].iloc[t]
    truncated = {k: v[v["date"] <= cut_date] for k, v in frames.items()}
    part = _frame(truncated, 2)
    pd.testing.assert_series_equal(full.loc[cut_date], part.loc[cut_date])
