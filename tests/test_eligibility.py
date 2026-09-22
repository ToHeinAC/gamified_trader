import numpy as np
import pandas as pd

from app.eligibility import FUTURE, MIN_DATE, MIN_HISTORY, eligible_mask
from app.indicators import with_indicators
from tests.helpers import make_bars


def _base_bars(n: int, *, start: str = "2001-01-02", volume: int = 1_000_000) -> pd.DataFrame:
    return make_bars([50.0] * n, start=start, volume=volume)


def test_base_case() -> None:
    n = 1600
    ind = with_indicators(_base_bars(n))
    mask = eligible_mask(ind)
    expected = np.zeros(n, dtype=bool)
    expected[249:1480] = True
    assert (mask == expected).all()


def test_date_before_2000() -> None:
    n = 1900
    bars = _base_bars(n, start="1998-01-02")
    ind = with_indicators(bars)
    mask = eligible_mask(ind)
    before = (ind["date"] < MIN_DATE).to_numpy()
    assert not mask[before].any()

    after_start = int(np.argmax(~before))
    lo = max(after_start, MIN_HISTORY - 1)
    hi = n - 1 - FUTURE
    assert mask[lo : hi + 1].all()


def test_gap_more_than_10_days_excludes_window() -> None:
    n = 1600
    bars = _base_bars(n)
    dates = list(bars["date"])
    shifted = [d + pd.Timedelta(days=15) if i >= 801 else d for i, d in enumerate(dates)]
    bars = bars.assign(date=pd.Series(shifted).astype("datetime64[ns]"))
    ind = with_indicators(bars)
    mask = eligible_mask(ind)
    assert not mask[681:1051].any()
    assert mask[680]
    assert mask[1051]


def test_gap_exactly_10_days_is_fine() -> None:
    n = 1600
    bars = _base_bars(n)
    dates = list(bars["date"])
    original_gap = (dates[801] - dates[800]).days
    offset = pd.Timedelta(days=10 - original_gap)
    shifted = [d + offset if i >= 801 else d for i, d in enumerate(dates)]
    bars = bars.assign(date=pd.Series(shifted).astype("datetime64[ns]"))
    ind = with_indicators(bars)
    mask = eligible_mask(ind)
    assert mask[249:1480].all()


def test_close_below_min_none_eligible() -> None:
    ind = with_indicators(make_bars([0.5] * 1600))
    assert not eligible_mask(ind).any()


def test_low_turnover_none_eligible() -> None:
    ind = with_indicators(_base_bars(1600, volume=1000))
    assert not eligible_mask(ind).any()


def test_too_short_history() -> None:
    assert not eligible_mask(with_indicators(_base_bars(369))).any()


def test_minimal_valid_history() -> None:
    mask = eligible_mask(with_indicators(_base_bars(370)))
    assert mask.tolist() == [i == 249 for i in range(370)]
