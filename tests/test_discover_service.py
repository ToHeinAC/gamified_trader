"""Tests for app.discover_service (PRD M8): loading, caching and fallback."""

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import cli, discover_service, model_store, universe, yahoo
from app.config import load_config
from app.discover import ModelBundle
from app.discover_store import DiscoverStore, MetaEntry
from app.price_store import PriceStore
from tests.helpers import random_walk_bars, write_store


def _cfg(tmp_path: Path):
    return load_config({"GT_DATA_DIR": str(tmp_path)})


def test_load_fetches_once_per_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path)
    calls: list[str] = []

    def fake_fetch_history(ticker: str) -> pd.DataFrame:
        calls.append(ticker)
        return random_walk_bars(300, seed=1, start="2025-01-02")

    monkeypatch.setattr(yahoo, "fetch_history", fake_fetch_history)
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: "EQUITY")

    today = date(2026, 9, 23)
    service = discover_service.DiscoverService(cfg, today=lambda: today)
    service.load("AAA")
    service.load("AAA")
    assert calls == ["AAA"]

    service_next_day = discover_service.DiscoverService(cfg, today=lambda: date(2026, 9, 24))
    service_next_day.load("AAA")
    assert calls == ["AAA", "AAA"]


def test_universe_ticker_skips_quote_type_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(universe, "ticker_names", lambda: {"AAPL": "Apple Inc."})
    monkeypatch.setattr(
        yahoo, "fetch_history", lambda t: random_walk_bars(300, seed=1, start="2025-01-02")
    )
    calls: list[str] = []
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: calls.append(t) or "EQUITY")

    service = discover_service.DiscoverService(cfg, today=lambda: date(2026, 9, 23))
    loaded = service.load("AAPL")

    assert calls == []
    assert loaded.quote_type == "EQUITY"


def test_non_universe_ticker_calls_quote_type_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(universe, "ticker_names", lambda: {})
    monkeypatch.setattr(
        yahoo, "fetch_history", lambda t: random_walk_bars(300, seed=1, start="2025-01-02")
    )
    calls: list[str] = []
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: calls.append(t) or "ETF")

    today = date(2026, 9, 23)
    service = discover_service.DiscoverService(cfg, today=lambda: today)
    service.load("SPY")
    assert calls == ["SPY"]

    # same-day reload: no new fetch at all, so no new quote-type call
    service.load("SPY")
    assert calls == ["SPY"]


def test_fetch_failure_falls_back_to_cache_and_marks_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    store = DiscoverStore(cfg.discover_dir)
    bars = random_walk_bars(300, seed=2, start="2025-01-02")
    store.write_bars("AAA", bars)
    store.set_meta("AAA", MetaEntry(fetched=date(2026, 9, 20), quote_type="EQUITY"))

    def fake_fetch_history(ticker: str) -> pd.DataFrame:
        raise RuntimeError("network down")

    monkeypatch.setattr(yahoo, "fetch_history", fake_fetch_history)
    service = discover_service.DiscoverService(cfg, today=lambda: date(2026, 9, 23))

    loaded = service.load("AAA")

    assert loaded.stale is True
    assert loaded.quote_type == "EQUITY"
    assert len(loaded.bars) > 0


def test_fetch_failure_without_cache_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(yahoo, "fetch_history", lambda t: None)
    service = discover_service.DiscoverService(cfg, today=lambda: date(2026, 9, 23))

    with pytest.raises(discover_service.DiscoverError, match="Keine Kursdaten"):
        service.load("ZZZ")


def test_pool_untouched_by_discover_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(tmp_path)
    pool_tickers = ["AAA", "BBB", "CCC", "DDD"]
    frames = {
        t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(pool_tickers)
    }
    write_store(cfg.prices_dir, frames)

    monkeypatch.setattr(
        yahoo, "fetch_history", lambda t: random_walk_bars(300, seed=9, start="2025-01-02")
    )
    monkeypatch.setattr(yahoo, "fetch_quote_type", lambda t: "EQUITY")
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    service = discover_service.DiscoverService(cfg, today=lambda: date(2026, 9, 23))
    service.load("NEWTICKER")

    assert PriceStore(cfg.prices_dir).tickers() == pool_tickers

    assert cli.main(["snapshots", "build", "--n", "60", "--seed", "1"]) == 0
    pool_df = pd.read_parquet(cfg.snapshots_parquet)
    assert "NEWTICKER" not in set(pool_df["ticker"])


def test_load_bundle_cache_reloads_on_touch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    model_store.write_model(
        {(1, 10, 0.5): object()}, {"seed": 1}, cfg.model_path, cfg.model_meta_path
    )
    discover_service._load_bundle_cached.cache_clear()
    read_calls = {"n": 0}
    orig_read_model = model_store.read_model

    def counting_read_model(path: Path) -> dict[tuple[int, int, float], object]:
        read_calls["n"] += 1
        return orig_read_model(path)

    monkeypatch.setattr(model_store, "read_model", counting_read_model)

    bundle1 = discover_service.load_bundle(cfg)
    bundle2 = discover_service.load_bundle(cfg)
    assert read_calls["n"] == 1
    assert isinstance(bundle1, ModelBundle)
    assert bundle1 is bundle2

    touched = cfg.model_meta_path.stat().st_mtime + 1
    os.utime(cfg.model_meta_path, (touched, touched))
    bundle3 = discover_service.load_bundle(cfg)
    assert read_calls["n"] == 2
    assert bundle3 is not bundle1


def test_load_bundle_missing_files_is_none(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert discover_service.load_bundle(cfg) is None


def test_load_market_and_pool_features_missing_is_none(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert discover_service.load_market(cfg) is None
    assert discover_service.load_pool_features(cfg) is None


def test_load_market_reads_existing_file(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    idx = pd.DatetimeIndex([pd.Timestamp("2026-09-20")], name="date")
    market = pd.DataFrame({"mkt_ret_20": [0.01]}, index=idx)
    model_store.write_market(market, cfg.market_parquet)

    loaded = discover_service.load_market(cfg)

    assert loaded is not None
    assert loaded.index.max() == pd.Timestamp("2026-09-20")


def test_load_pool_features_reads_existing_file(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    features = pd.DataFrame({"snapshot_id": ["a"], "ret_5": [0.02]})
    model_store.write_features(features, cfg.features_parquet)

    loaded = discover_service.load_pool_features(cfg)

    assert loaded is not None
    assert loaded["snapshot_id"].tolist() == ["a"]
