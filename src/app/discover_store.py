"""Discover cache: bars via PriceStore, plus per-ticker fetch metadata (PRD M8, A21)."""

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app.price_store import PriceStore


@dataclass(frozen=True)
class MetaEntry:
    fetched: date
    quote_type: str | None


class DiscoverStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._prices = PriceStore(root)
        self._meta_path = root / "meta.json"

    def read_bars(self, ticker: str) -> pd.DataFrame | None:
        if not self._prices.has(ticker):
            return None
        return self._prices.read(ticker)

    def write_bars(self, ticker: str, df: pd.DataFrame) -> None:
        self._prices.write(ticker, df)

    def _read_all_meta(self) -> dict[str, dict[str, str | None]]:
        if not self._meta_path.exists():
            return {}
        return json.loads(self._meta_path.read_text(encoding="utf-8"))

    def meta(self, ticker: str) -> MetaEntry | None:
        raw = self._read_all_meta().get(ticker)
        if raw is None:
            return None
        fetched = date.fromisoformat(str(raw["fetched"]))
        quote_type = raw.get("quote_type")
        return MetaEntry(fetched=fetched, quote_type=quote_type)

    def set_meta(self, ticker: str, entry: MetaEntry) -> None:
        all_meta = self._read_all_meta()
        all_meta[ticker] = {"fetched": entry.fetched.isoformat(), "quote_type": entry.quote_type}
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._meta_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(all_meta, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, self._meta_path)
