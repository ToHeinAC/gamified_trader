from pathlib import Path

import pandas as pd
import pytest

from app.price_store import PriceStore
from tests.helpers import make_bars


def test_write_read_round_trip(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df = make_bars([10.0, 11.0, 12.0])
    store.write("AAA", df)
    pd.testing.assert_frame_equal(store.read("AAA"), df)


def test_last_date(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df = make_bars([10.0, 11.0, 12.0])
    store.write("AAA", df)
    assert store.last_date("AAA") == df["date"].iloc[-1].date()
    assert store.last_date("BBB") is None


def test_tickers_sorted_and_has(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    store.write("BBB", make_bars([1.0]))
    store.write("AAA", make_bars([1.0]))
    assert store.tickers() == ["AAA", "BBB"]
    assert store.has("AAA")
    assert not store.has("CCC")


def test_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    store.write("AAA", make_bars([1.0, 2.0]))
    assert not (tmp_path / "AAA.parquet.tmp").exists()


def test_write_unsorted_dates_raises(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df = make_bars([1.0, 2.0, 3.0])
    shuffled = df.iloc[[1, 0, 2]].reset_index(drop=True)
    with pytest.raises(ValueError, match="ascending"):
        store.write("AAA", shuffled)


def test_bad_ticker_path(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    with pytest.raises(ValueError, match="invalid ticker"):
        store.path("")
    with pytest.raises(ValueError, match="invalid ticker"):
        store.path("A/B")
