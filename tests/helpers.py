"""Shared test factories for synthetic price frames."""

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from app.price_store import PriceStore


def make_bars(
    closes: Sequence[float],
    *,
    start: str = "2001-01-02",
    spread: float = 0.01,
    volume: int = 1_000_000,
) -> pd.DataFrame:
    """Valid OHLCV frame on business days.

    open = previous close (first row: close), high = max(open, close) * (1 + spread),
    low = min(open, close) * (1 - spread).
    """
    dates = pd.bdate_range(start=start, periods=len(closes))
    opens = [closes[0], *closes[:-1]]
    highs = [max(o, c) * (1 + spread) for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) * (1 - spread) for o, c in zip(opens, closes, strict=True)]
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
            "open": pd.Series(opens, dtype="float64"),
            "high": pd.Series(highs, dtype="float64"),
            "low": pd.Series(lows, dtype="float64"),
            "close": pd.Series(closes, dtype="float64"),
            "volume": pd.Series([volume] * len(closes), dtype="int64"),
        }
    )


def random_walk_bars(
    n: int,
    seed: int,
    *,
    start_price: float = 50.0,
    sigma: float = 0.02,
    start: str = "2001-01-02",
) -> pd.DataFrame:
    """closes = start_price * exp(cumsum(normal(0, sigma))) with default_rng(seed)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma, size=n)
    closes = start_price * np.exp(np.cumsum(steps))
    return make_bars(closes.tolist(), start=start)


def write_store(root: Path, frames: Mapping[str, pd.DataFrame]) -> PriceStore:
    store = PriceStore(root)
    for ticker, df in frames.items():
        store.write(ticker, df)
    return store
