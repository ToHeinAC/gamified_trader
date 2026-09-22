"""Pure OHLCV cleaning rules (PRD M1)."""

from dataclasses import dataclass

import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class CleanStats:
    rows_in: int
    dropped_invalid: int
    dropped_duplicates: int
    high_fixed: int
    low_fixed: int

    @property
    def corrections(self) -> int:
        return self.high_fixed + self.low_fixed


def clean_prices(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleanStats]:
    rows_in = len(raw)
    df = raw.copy()
    df["volume"] = df["volume"].fillna(0)

    invalid = df[list(PRICE_COLUMNS)].isna().any(axis=1) | (df[list(PRICE_COLUMNS)] <= 0).any(
        axis=1
    )
    dropped_invalid = int(invalid.sum())
    df = df.loc[~invalid]

    before_dedup = len(df)
    df = df.drop_duplicates("date", keep="last")
    dropped_duplicates = before_dedup - len(df)

    df = df.sort_values("date", kind="stable").reset_index(drop=True)

    correct_high = df[["open", "close"]].max(axis=1)
    correct_low = df[["open", "close"]].min(axis=1)
    high_fixed = int((df["high"] < correct_high).sum())
    low_fixed = int((df["low"] > correct_low).sum())
    df["high"] = df["high"].where(df["high"] >= correct_high, correct_high)
    df["low"] = df["low"].where(df["low"] <= correct_low, correct_low)

    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    for col in PRICE_COLUMNS:
        df[col] = df[col].astype("float64")
    df["volume"] = df["volume"].round().astype("int64")
    df = df[list(COLUMNS)]

    stats = CleanStats(
        rows_in=rows_in,
        dropped_invalid=dropped_invalid,
        dropped_duplicates=dropped_duplicates,
        high_fixed=high_fixed,
        low_fixed=low_fixed,
    )
    return df, stats
