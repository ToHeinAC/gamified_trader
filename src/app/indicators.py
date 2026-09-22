"""Pure technical indicators (PRD R1). Wilder smoothing shared by RSI and ATR (D4)."""

import numpy as np
import pandas as pd

SMA_FAST, SMA_SLOW = 50, 200
BB_N, BB_K = 20, 2.0
RSI_N = ATR_N = 14
INDICATOR_COLUMNS = ("sma50", "sma200", "bb_upper", "bb_mid", "bb_lower", "rsi14", "atr14")


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def bollinger(
    close: pd.Series, n: int = BB_N, k: float = BB_K
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(n, min_periods=n).mean()
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return mid + k * std, mid, mid - k * std


def _wilder(
    x: np.ndarray[tuple[int], np.dtype[np.float64]], n: int
) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
    """x[0] is unused. out[i] = NaN for i < n; out[n] = mean(x[1:n+1]);
    out[i] = (out[i-1] * (n-1) + x[i]) / n for i > n. All NaN if len(x) <= n."""
    out = np.full(len(x), np.nan, dtype=np.float64)
    if len(x) <= n:
        return out
    out[n] = float(np.mean(x[1 : n + 1]))
    for i in range(n + 1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def rsi_wilder(close: pd.Series, n: int = RSI_N) -> pd.Series:
    diff = close.diff()
    gains = diff.clip(lower=0.0).to_numpy(dtype=np.float64)
    losses = (-diff).clip(lower=0.0).to_numpy(dtype=np.float64)
    ag = _wilder(gains, n)
    al = _wilder(losses, n)

    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100.0 - 100.0 / (1.0 + ag / al)
    rsi[(al == 0) & (ag > 0)] = 100.0
    rsi[(ag == 0) & (al == 0)] = 50.0
    return pd.Series(rsi, index=close.index)


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, n: int = ATR_N) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1, skipna=False
    )
    return pd.Series(_wilder(tr.to_numpy(dtype=np.float64), n), index=close.index)


def with_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy()
    df["sma50"] = sma(df["close"], SMA_FAST)
    df["sma200"] = sma(df["close"], SMA_SLOW)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger(df["close"])
    df["rsi14"] = rsi_wilder(df["close"])
    df["atr14"] = atr_wilder(df["high"], df["low"], df["close"])
    return df
