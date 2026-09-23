"""Equal-weight market-regime features per date from all tickers of the price store (PRD R12, A26).

Causal: the row at date t uses only bars <= t. Returns are per ticker over its own bars.
"""

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

MIN_TICKERS = 30
GLITCH = 0.5
RET_WINDOWS = (20, 60, 250)
SMA_WINDOW = 200
VOLA_WINDOW = 20
MARKET_COLUMNS = (
    "mkt_ret_20",
    "mkt_ret_60",
    "mkt_ret_250",
    "mkt_dist_sma200",
    "mkt_vola20",
    "mkt_breadth200",
)

LoadFn = Callable[[str], pd.DataFrame]


def _ticker_series(bars: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Daily return (|r| > GLITCH -> NaN) and close > SMA200 as 0/1 (NaN before SMA200 exists)."""
    close = pd.Series(
        bars["close"].to_numpy(dtype=np.float64), index=pd.DatetimeIndex(bars["date"])
    )
    ret = close.pct_change()
    ret = ret.where(ret.abs() <= GLITCH)
    sma = close.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    above = (close > sma).astype("float64").where(sma.notna())
    return ret, above


def _wide(tickers: Sequence[str], load: LoadFn) -> tuple[pd.DataFrame, pd.DataFrame]:
    rets: dict[str, pd.Series] = {}
    aboves: dict[str, pd.Series] = {}
    for ticker in sorted(tickers):
        rets[ticker], aboves[ticker] = _ticker_series(load(ticker))
    return pd.concat(rets, axis=1, sort=True), pd.concat(aboves, axis=1, sort=True)


def _mean_if_enough(wide: pd.DataFrame, min_tickers: int) -> pd.Series:
    return wide.mean(axis=1).where(wide.notna().sum(axis=1) >= min_tickers)


def market_return(
    tickers: Sequence[str], load: LoadFn, min_tickers: int = MIN_TICKERS
) -> pd.Series:
    """m_t: mean daily return of the tickers with a return at t; NaN with fewer than min_tickers."""
    rets, _aboves = _wide(tickers, load)
    return _mean_if_enough(rets, min_tickers)


def market_frame(
    tickers: Sequence[str], load: LoadFn, min_tickers: int = MIN_TICKERS
) -> pd.DataFrame:
    """Index `date` = union of all tickers' dates; columns MARKET_COLUMNS; thin dates all NaN."""
    rets, aboves = _wide(tickers, load)
    m = _mean_if_enough(rets, min_tickers)
    index = (1 + m.fillna(0.0)).cumprod()
    out = pd.DataFrame(index=rets.index)
    for k in RET_WINDOWS:
        out[f"mkt_ret_{k}"] = index / index.shift(k) - 1
    out["mkt_dist_sma200"] = index / index.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean() - 1
    out["mkt_vola20"] = m.rolling(VOLA_WINDOW, min_periods=VOLA_WINDOW).std(ddof=0)
    out["mkt_breadth200"] = _mean_if_enough(aboves, min_tickers)
    out = out.where(m.notna())
    out.index.name = "date"
    return out[list(MARKET_COLUMNS)]
