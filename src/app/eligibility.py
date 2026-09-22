"""Snapshot eligibility mask per bar (PRD R10). Pure, no I/O."""

import numpy as np
import pandas as pd

MIN_DATE = pd.Timestamp("2000-01-01")
MIN_HISTORY = 250
FUTURE = 120
GAP_WINDOW_BACK = 250
MAX_GAP_DAYS = 10
MIN_CLOSE = 1.0
MIN_MEDIAN_TURNOVER = 1_000_000.0
TURNOVER_WINDOW = 20
MIN_SPACING = 20


_IntArray = np.ndarray[tuple[int], np.dtype[np.int64]]
_BoolArray = np.ndarray[tuple[int], np.dtype[np.bool_]]


def _no_gap_nearby(date: pd.Series, n: int) -> _BoolArray:
    gap_days = date.diff().dt.days
    bad: _BoolArray = (gap_days > MAX_GAP_DAYS).fillna(False).to_numpy()
    # numpy's own overloads for cumsum are ambiguous under strict mode (verified in isolation).
    cum: _IntArray = np.cumsum(bad.astype(np.int64))  # pyright: ignore[reportUnknownMemberType]

    idx: _IntArray = np.arange(n)
    lo: _IntArray = np.maximum(1, idx - (GAP_WINDOW_BACK - 1))
    hi: _IntArray = np.minimum(n - 1, idx + FUTURE)
    lo_minus1 = lo - 1
    # Same numpy stub gap as np.cumsum above.
    total_bad: _IntArray = cum[hi] - np.where(  # pyright: ignore[reportUnknownMemberType]
        lo_minus1 >= 0, cum[lo_minus1], 0
    )
    return total_bad == 0


def eligible_mask(ind: pd.DataFrame) -> _BoolArray:
    n = len(ind)
    idx: _IntArray = np.arange(n)

    cond_date = (ind["date"] >= MIN_DATE).to_numpy()
    cond_range = (idx >= MIN_HISTORY - 1) & (idx <= n - 1 - FUTURE)
    cond_gap = _no_gap_nearby(ind["date"], n)
    cond_close = (ind["close"] >= MIN_CLOSE).to_numpy()

    turnover = (
        (ind["close"] * ind["volume"])
        .rolling(TURNOVER_WINDOW, min_periods=TURNOVER_WINDOW)
        .median()
    )
    cond_turnover = (turnover >= MIN_MEDIAN_TURNOVER).fillna(False).to_numpy()
    cond_atr = (ind["atr14"] > 0).fillna(False).to_numpy()

    return cond_date & cond_range & cond_gap & cond_close & cond_turnover & cond_atr
