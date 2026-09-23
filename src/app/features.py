"""Pure ML features per bar (PRD R12). Causal: row t uses only bars <= t."""

import numpy as np
import pandas as pd

from app.signals import EVENTS

RET_WINDOWS = (5, 20, 60, 120, 250)
SLOPE_WINDOW = 20
RSI_CHANGE_WINDOW = 5
BB_WIDTH_RANK_WINDOW = 126
VOLUME_WINDOW = 20
VOLA_WINDOW = 20
EXTREME_WINDOW = 252

NUMERIC_FEATURES = (
    "ret_5",
    "ret_20",
    "ret_60",
    "ret_120",
    "ret_250",
    "dist_sma50",
    "dist_sma200",
    "sma_ratio",
    "slope_sma50",
    "slope_sma200",
    "rsi",
    "rsi_chg5",
    "bb_pctb",
    "bb_width",
    "bb_width_rank",
    "vol_rel",
    "atr_pct",
    "vola20",
    "dist_high252",
    "dist_low252",
)
FEATURE_COLUMNS = NUMERIC_FEATURES + tuple(f"sig_{event}" for event in EVENTS)


def _percentile_rank(window: np.ndarray[tuple[int], np.dtype[np.float64]]) -> float:
    return float((window <= window[-1]).mean())


def compute_features(ind: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Input: bars with indicators (M2) and R11 flags (M4), same index. 29 columns (R12)."""
    close, high, low, volume = ind["close"], ind["high"], ind["low"], ind["volume"]
    out = pd.DataFrame(index=ind.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        for n in RET_WINDOWS:
            out[f"ret_{n}"] = close / close.shift(n) - 1
        out["dist_sma50"] = close / ind["sma50"] - 1
        out["dist_sma200"] = close / ind["sma200"] - 1
        out["sma_ratio"] = ind["sma50"] / ind["sma200"] - 1
        out["slope_sma50"] = ind["sma50"] / ind["sma50"].shift(SLOPE_WINDOW) - 1
        out["slope_sma200"] = ind["sma200"] / ind["sma200"].shift(SLOPE_WINDOW) - 1
        out["rsi"] = ind["rsi14"]
        out["rsi_chg5"] = ind["rsi14"] - ind["rsi14"].shift(RSI_CHANGE_WINDOW)
        bb_range = ind["bb_upper"] - ind["bb_lower"]
        out["bb_pctb"] = (close - ind["bb_lower"]) / bb_range
        out["bb_width"] = bb_range / ind["bb_mid"]
        out["bb_width_rank"] = (
            out["bb_width"]
            .rolling(BB_WIDTH_RANK_WINDOW, min_periods=BB_WIDTH_RANK_WINDOW)
            .apply(_percentile_rank, raw=True)
        )
        vol_baseline = volume.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).mean().shift(1)
        out["vol_rel"] = volume / vol_baseline
        out["atr_pct"] = ind["atr14"] / close
        daily_ret = close / close.shift(1) - 1
        out["vola20"] = daily_ret.rolling(VOLA_WINDOW, min_periods=VOLA_WINDOW).std(ddof=0)
        high_ext = high.rolling(EXTREME_WINDOW, min_periods=EXTREME_WINDOW).max()
        low_ext = low.rolling(EXTREME_WINDOW, min_periods=EXTREME_WINDOW).min()
        out["dist_high252"] = close / high_ext - 1
        out["dist_low252"] = close / low_ext - 1
        for event in EVENTS:
            out[f"sig_{event}"] = flags[f"sig_{event}"].astype("float64")
    return out[list(FEATURE_COLUMNS)]
