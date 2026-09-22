# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: plotly/yfinance ship no type stubs; untyped calls stay inside this module (PRD §5 risks).
"""The only module that imports yfinance."""

from collections.abc import Sequence
from datetime import date
from typing import Any, cast

import pandas as pd
import yfinance as yf

FIELDS = ("open", "high", "low", "close", "volume")


def fetch_batch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
    """One yf.download call. Returns normalized, uncleaned frames; empty tickers are absent."""
    kw: dict[str, Any] = {"period": "max"} if start is None else {"start": start.isoformat()}
    raw = yf.download(
        list(tickers),
        auto_adjust=True,
        actions=False,
        group_by="ticker",
        threads=False,
        progress=False,
        multi_level_index=True,
        **kw,
    )
    if raw is None or len(raw) == 0:
        return {}
    return split_download(raw, tickers)


def split_download(raw: pd.DataFrame, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
    if not isinstance(raw.columns, pd.MultiIndex):
        sub = normalize_frame(raw)
        return {} if sub["close"].isna().all() else {tickers[0]: sub}

    tickers_set = set(tickers)
    level = next(
        lvl
        for lvl in range(raw.columns.nlevels)
        if set(raw.columns.get_level_values(lvl)) & tickers_set
    )
    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        if ticker not in raw.columns.get_level_values(level):
            continue
        sub = normalize_frame(cast(pd.DataFrame, raw.xs(ticker, axis=1, level=level)))
        if sub["close"].isna().all():
            continue
        result[ticker] = sub
    return result


def normalize_frame(sub: pd.DataFrame) -> pd.DataFrame:
    df = sub.rename(columns=str.lower)
    for field in FIELDS:
        if field not in df.columns:
            df[field] = pd.NA
    df = df[list(FIELDS)].copy()

    index = df.index
    if isinstance(index, pd.DatetimeIndex) and index.tz is not None:
        index = index.tz_localize(None)
    df["date"] = pd.DatetimeIndex(index).normalize().astype("datetime64[ns]")
    df = df.reset_index(drop=True)

    all_nan = df[["open", "high", "low", "close"]].isna().all(axis=1)
    return df.loc[~all_nan, ["date", *FIELDS]].reset_index(drop=True)
