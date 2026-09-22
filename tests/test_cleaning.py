import numpy as np
import pandas as pd

from app.cleaning import COLUMNS, clean_prices
from tests.helpers import make_bars


def test_drops_invalid_rows() -> None:
    df = make_bars([10.0, 11.0, 12.0, 13.0, 14.0])
    df.loc[0, "open"] = np.nan
    df.loc[1, "close"] = 0.0
    df.loc[2, "low"] = 0.0
    cleaned, stats = clean_prices(df)
    assert stats.dropped_invalid == 3
    assert len(cleaned) == 2


def test_duplicate_keeps_last() -> None:
    df = make_bars([10.0, 11.0])
    dup = df.iloc[[1]].copy()
    dup["close"] = 99.0
    df = pd.concat([df, dup], ignore_index=True)
    cleaned, stats = clean_prices(df)
    assert stats.dropped_duplicates == 1
    row = cleaned[cleaned["date"] == df.loc[1, "date"]]
    assert row["close"].iloc[0] == 99.0


def test_unsorted_input_is_sorted() -> None:
    df = make_bars([10.0, 11.0, 12.0])
    shuffled = df.iloc[[2, 0, 1]].copy()
    cleaned, _ = clean_prices(shuffled)
    assert list(cleaned["date"]) == sorted(cleaned["date"])
    assert list(cleaned.index) == [0, 1, 2]


def test_high_low_corrected() -> None:
    df = make_bars([10.0, 11.0])
    df.loc[0, "high"] = 5.0  # below max(open, close)
    df.loc[1, "low"] = 100.0  # above min(open, close)
    cleaned, stats = clean_prices(df)
    assert cleaned.loc[0, "high"] == max(df["open"].iloc[0], df["close"].iloc[0])
    assert cleaned.loc[1, "low"] == min(df["open"].iloc[1], df["close"].iloc[1])
    assert stats.high_fixed == 1
    assert stats.low_fixed == 1
    assert stats.corrections == 2


def test_volume_nan_becomes_zero() -> None:
    df = make_bars([10.0, 11.0])
    df.loc[0, "volume"] = np.nan
    cleaned, _ = clean_prices(df)
    assert cleaned["volume"].dtype == np.int64
    assert cleaned.loc[0, "volume"] == 0


def test_dtypes_and_column_order() -> None:
    df = make_bars([10.0, 11.0])
    cleaned, _ = clean_prices(df)
    assert list(cleaned.columns) == list(COLUMNS)
    assert cleaned["date"].dtype == "datetime64[ns]"
    for col in ("open", "high", "low", "close"):
        assert cleaned[col].dtype == np.float64
    assert cleaned["volume"].dtype == np.int64
