"""Parquet-backed price storage: data/prices/<TICKER>.parquet."""

import os
from datetime import date
from pathlib import Path

import pandas as pd

from app.cleaning import COLUMNS


class PriceStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, ticker: str) -> Path:
        if not ticker or "/" in ticker:
            raise ValueError(f"invalid ticker: {ticker!r}")
        return self._root / f"{ticker}.parquet"

    def has(self, ticker: str) -> bool:
        return self.path(ticker).exists()

    def tickers(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(p.stem for p in self._root.glob("*.parquet"))

    def read(self, ticker: str) -> pd.DataFrame:
        return pd.read_parquet(self.path(ticker))

    def write(self, ticker: str, df: pd.DataFrame) -> None:
        if list(df.columns) != list(COLUMNS):
            raise ValueError(f"expected columns {COLUMNS}, got {tuple(df.columns)}")
        if not df["date"].is_monotonic_increasing or df["date"].duplicated().any():
            raise ValueError("dates must be strictly ascending")

        path = self.path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)

    def last_date(self, ticker: str) -> date | None:
        if not self.has(ticker):
            return None
        df = self.read(ticker)
        if df.empty:
            return None
        last = df["date"].iloc[-1]
        return last.date()
