"""Signal flags per bar (PRD R11). Pure, no I/O."""

import pandas as pd

EVENTS = (
    "GOLDEN_CROSS",
    "DEATH_CROSS",
    "SMA200_UP",
    "SMA200_DOWN",
    "RSI_LT_30",
    "RSI_GT_70",
    "CLOSE_GT_UPPER_BB",
    "CLOSE_LT_LOWER_BB",
    "VOLUME_SPIKE",
)

EVENT_LABELS: dict[str, str] = {
    "GOLDEN_CROSS": "Golden Cross: SMA50 kreuzt SMA200 aufwärts",
    "DEATH_CROSS": "Death Cross: SMA50 kreuzt SMA200 abwärts",
    "SMA200_UP": "Kurs kreuzt SMA200 aufwärts",
    "SMA200_DOWN": "Kurs kreuzt SMA200 abwärts",
    "RSI_LT_30": "RSI14 unter 30 (überverkauft)",
    "RSI_GT_70": "RSI14 über 70 (überkauft)",
    "CLOSE_GT_UPPER_BB": "Kurs über oberem Bollinger-Band",
    "CLOSE_LT_LOWER_BB": "Kurs unter unterem Bollinger-Band",
    "VOLUME_SPIKE": "Volumen-Spike (über 200 % des 20-Tage-Schnitts)",
}

CROSS_LOOKBACK = 3
_VOLUME_WINDOW = 20
_VOLUME_FACTOR = 2.0


def cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.shift(1) <= b.shift(1)) & (a > b)


def cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.shift(1) >= b.shift(1)) & (a < b)


def recent(x: pd.Series, k: int = CROSS_LOOKBACK) -> pd.Series:
    out = pd.Series(False, index=x.index)
    for shift in range(k):
        out = out | x.shift(shift).fillna(False).astype(bool)
    return out


def signal_flags(ind: pd.DataFrame) -> pd.DataFrame:
    """Input: bars with indicators (M2). One bool column per event, plus is_signal_day."""
    close, volume = ind["close"], ind["volume"]
    flags = pd.DataFrame(index=ind.index)
    flags["sig_GOLDEN_CROSS"] = recent(cross_up(ind["sma50"], ind["sma200"]))
    flags["sig_DEATH_CROSS"] = recent(cross_down(ind["sma50"], ind["sma200"]))
    flags["sig_SMA200_UP"] = recent(cross_up(close, ind["sma200"]))
    flags["sig_SMA200_DOWN"] = recent(cross_down(close, ind["sma200"]))
    flags["sig_RSI_LT_30"] = (ind["rsi14"] < 30).fillna(False)
    flags["sig_RSI_GT_70"] = (ind["rsi14"] > 70).fillna(False)
    flags["sig_CLOSE_GT_UPPER_BB"] = (close > ind["bb_upper"]).fillna(False)
    flags["sig_CLOSE_LT_LOWER_BB"] = (close < ind["bb_lower"]).fillna(False)
    baseline = volume.rolling(_VOLUME_WINDOW, min_periods=_VOLUME_WINDOW).mean().shift(1)
    flags["sig_VOLUME_SPIKE"] = (volume > _VOLUME_FACTOR * baseline).fillna(False)
    flags["is_signal_day"] = flags[[f"sig_{event}" for event in EVENTS]].any(axis=1)
    return flags
