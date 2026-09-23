"""Round-trip tests for app.discover_store."""

from datetime import date
from pathlib import Path

from app.discover_store import DiscoverStore, MetaEntry
from tests.helpers import make_bars


def test_bars_round_trip(tmp_path: Path) -> None:
    store = DiscoverStore(tmp_path)
    assert store.read_bars("AAPL") is None

    bars = make_bars([10.0, 11.0, 12.0])
    store.write_bars("AAPL", bars)
    loaded = store.read_bars("AAPL")

    assert loaded is not None
    assert loaded["close"].tolist() == bars["close"].tolist()


def test_meta_round_trip(tmp_path: Path) -> None:
    store = DiscoverStore(tmp_path)
    assert store.meta("AAPL") is None

    store.set_meta("AAPL", MetaEntry(fetched=date(2026, 9, 23), quote_type="EQUITY"))
    entry = store.meta("AAPL")

    assert entry == MetaEntry(fetched=date(2026, 9, 23), quote_type="EQUITY")


def test_meta_preserves_other_tickers_and_is_sorted(tmp_path: Path) -> None:
    store = DiscoverStore(tmp_path)
    store.set_meta("BBB", MetaEntry(fetched=date(2026, 9, 20), quote_type="ETF"))
    store.set_meta("AAA", MetaEntry(fetched=date(2026, 9, 23), quote_type=None))

    assert store.meta("BBB") == MetaEntry(fetched=date(2026, 9, 20), quote_type="ETF")
    assert store.meta("AAA") == MetaEntry(fetched=date(2026, 9, 23), quote_type=None)
    meta_text = (tmp_path / "meta.json").read_text(encoding="utf-8")
    assert meta_text.index('"AAA"') < meta_text.index('"BBB"')


def test_no_tmp_files_left(tmp_path: Path) -> None:
    store = DiscoverStore(tmp_path)
    store.write_bars("AAA", make_bars([10.0, 11.0]))
    store.set_meta("AAA", MetaEntry(fetched=date(2026, 9, 23), quote_type="EQUITY"))
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"AAA.parquet", "meta.json"}
