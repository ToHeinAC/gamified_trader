"""Orchestration for Entdeckungsmodus: cache, Yahoo fallback, model/market/pool caching (PRD M8)."""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app import discover, model_store, universe, yahoo
from app.cleaning import clean_prices
from app.config import Config
from app.discover import Analysis, ModelBundle
from app.discover_store import DiscoverStore, MetaEntry
from app.indicators import with_indicators


class DiscoverError(Exception):
    pass


@dataclass(frozen=True)
class Loaded:
    bars: pd.DataFrame
    quote_type: str | None
    stale: bool
    data_as_of: date


@functools.lru_cache(maxsize=2)
def _load_bundle_cached(
    model_path_str: str, _model_mtime_ns: int, meta_path_str: str, _meta_mtime_ns: int
) -> ModelBundle:
    models = model_store.read_model(Path(model_path_str))
    meta = model_store.read_meta(Path(meta_path_str))
    return ModelBundle(models=models, meta=meta)


def load_bundle(cfg: Config) -> ModelBundle | None:
    if not cfg.model_path.exists() or not cfg.model_meta_path.exists():
        return None
    return _load_bundle_cached(
        str(cfg.model_path),
        cfg.model_path.stat().st_mtime_ns,
        str(cfg.model_meta_path),
        cfg.model_meta_path.stat().st_mtime_ns,
    )


@functools.lru_cache(maxsize=2)
def _load_market_cached(path_str: str, _mtime_ns: int) -> pd.DataFrame:
    return model_store.read_market(Path(path_str))


def load_market(cfg: Config) -> pd.DataFrame | None:
    if not cfg.market_parquet.exists():
        return None
    return _load_market_cached(str(cfg.market_parquet), cfg.market_parquet.stat().st_mtime_ns)


@functools.lru_cache(maxsize=2)
def _load_pool_features_cached(path_str: str, _mtime_ns: int) -> pd.DataFrame:
    return model_store.read_features(Path(path_str))


def load_pool_features(cfg: Config) -> pd.DataFrame | None:
    if not cfg.features_parquet.exists():
        return None
    return _load_pool_features_cached(
        str(cfg.features_parquet), cfg.features_parquet.stat().st_mtime_ns
    )


class DiscoverService:
    def __init__(self, cfg: Config, today: Callable[[], date] = date.today) -> None:
        self.cfg = cfg
        self._today = today
        self._store = DiscoverStore(cfg.discover_dir)

    def _quote_type(self, ticker: str, entry: MetaEntry | None) -> str | None:
        if ticker in universe.ticker_names():
            return "EQUITY"
        if entry is not None and entry.quote_type is not None:
            return entry.quote_type
        return yahoo.fetch_quote_type(ticker)

    def _fetch(
        self, ticker: str, entry: MetaEntry | None, today: date
    ) -> tuple[pd.DataFrame, str | None, bool]:
        try:
            raw = yahoo.fetch_history(ticker)
        except Exception:
            raw = None
        if raw is None:
            cached = self._store.read_bars(ticker)
            if cached is None:
                raise DiscoverError(f"Keine Kursdaten für {ticker} gefunden.")
            return cached, entry.quote_type if entry else None, True

        cleaned, _stats = clean_prices(raw)
        quote_type = self._quote_type(ticker, entry)
        self._store.write_bars(ticker, cleaned)
        self._store.set_meta(ticker, MetaEntry(fetched=today, quote_type=quote_type))
        return cleaned, quote_type, False

    def load(self, ticker: str) -> Loaded:
        entry = self._store.meta(ticker)
        today = self._today()
        if discover.needs_fetch(entry, today):
            bars, quote_type, stale = self._fetch(ticker, entry, today)
        else:
            cached = self._store.read_bars(ticker)
            if cached is None:
                raise DiscoverError(f"Keine Kursdaten für {ticker} gefunden.")
            bars, quote_type, stale = cached, entry.quote_type if entry else None, False

        completed = discover.completed_bars(bars, today)
        if completed.empty:
            raise DiscoverError(f"Keine abgeschlossenen Kerzen für {ticker}.")
        return Loaded(
            bars=completed,
            quote_type=quote_type,
            stale=stale,
            data_as_of=completed["date"].iloc[-1].date(),
        )

    def analyze(self, ticker: str) -> tuple[Loaded, Analysis]:
        loaded = self.load(ticker)
        ind = with_indicators(loaded.bars)
        result = discover.analyze(
            ticker,
            ind,
            loaded.quote_type,
            load_bundle(self.cfg),
            load_market(self.cfg),
            load_pool_features(self.cfg),
        )
        return loaded, result
