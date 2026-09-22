import numpy as np
import pandas as pd
import pytest

from app import yahoo
from app.cleaning import clean_prices
from app.price_store import PriceStore


def _shape1(index: pd.DatetimeIndex, values: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": values["open"],
            "High": values["high"],
            "Low": values["low"],
            "Close": values["close"],
            "Volume": values["volume"],
        },
        index=index,
    )


def _shape2(index: pd.DatetimeIndex, per_ticker: dict[str, dict[str, list[float]]]) -> pd.DataFrame:
    frames = {
        ticker: _shape1(index, values).rename(
            columns={
                "Open": "Open",
                "High": "High",
                "Low": "Low",
                "Close": "Close",
                "Volume": "Volume",
            }
        )
        for ticker, values in per_ticker.items()
    }
    return pd.concat(frames, axis=1)


def _shape3(index: pd.DatetimeIndex, per_ticker: dict[str, dict[str, list[float]]]) -> pd.DataFrame:
    fields = ("Open", "High", "Low", "Close", "Volume")
    cols: dict[tuple[str, str], list[float]] = {}
    for field in fields:
        key = field.lower()
        for ticker, values in per_ticker.items():
            cols[(field, ticker)] = values[key]
    return pd.DataFrame(cols, index=index)


def _numbers() -> dict[str, dict[str, list[float]]]:
    return {
        "AAA": {
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.2, 11.2, 12.2],
            "volume": [1000, 1100, 1200],
        }
    }


def test_three_shapes_give_the_same_result(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    index = pd.date_range("2024-01-02", periods=3, tz="America/New_York")
    numbers = _numbers()

    results: list[pd.DataFrame] = []
    for raw in (
        _shape1(index, numbers["AAA"]),
        _shape2(index, numbers),
        _shape3(index, numbers),
    ):
        monkeypatch.setattr(yahoo.yf, "download", lambda *a, _raw=raw, **kw: _raw)
        frames = yahoo.fetch_batch(["AAA"], None)
        cleaned, _ = clean_prices(frames["AAA"])
        store = PriceStore(tmp_path)
        store.write("AAA", cleaned)
        results.append(store.read("AAA"))

    pd.testing.assert_frame_equal(results[0], results[1])
    pd.testing.assert_frame_equal(results[0], results[2])


def test_nan_ticker_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.date_range("2024-01-02", periods=3)
    numbers = _numbers()
    numbers["BBB"] = {
        "open": [np.nan, np.nan, np.nan],
        "high": [np.nan, np.nan, np.nan],
        "low": [np.nan, np.nan, np.nan],
        "close": [np.nan, np.nan, np.nan],
        "volume": [np.nan, np.nan, np.nan],
    }
    raw = _shape2(index, numbers)
    monkeypatch.setattr(yahoo.yf, "download", lambda *a, **kw: raw)
    frames = yahoo.fetch_batch(["AAA", "BBB"], None)
    assert "BBB" not in frames
    assert "AAA" in frames


def test_none_response_gives_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yahoo.yf, "download", lambda *a, **kw: None)
    assert yahoo.fetch_batch(["AAA"], None) == {}


def test_period_vs_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_download(tickers: object, **kw: object) -> None:
        calls.append(kw)
        return None

    monkeypatch.setattr(yahoo.yf, "download", fake_download)
    yahoo.fetch_batch(["AAA"], None)
    yahoo.fetch_batch(["AAA"], __import__("datetime").date(2024, 1, 3))

    assert calls[0]["period"] == "max"
    assert "start" not in calls[0]
    assert calls[1]["start"] == "2024-01-03"
    assert "period" not in calls[1]
