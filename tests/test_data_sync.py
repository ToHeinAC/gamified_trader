from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import data_sync
from app.price_store import PriceStore
from tests.helpers import make_bars, write_store


def _sleep_recorder() -> tuple[list[float], data_sync.SleepFn]:
    sleeps: list[float] = []
    return sleeps, sleeps.append


def test_retry_then_success() -> None:
    sleeps, sleep = _sleep_recorder()
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    assert data_sync.call_with_retry(fn, sleep) == "ok"
    assert sleeps == [2.0, 4.0]


def test_retry_exhausted() -> None:
    sleeps, sleep = _sleep_recorder()

    def fn() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        data_sync.call_with_retry(fn, sleep)
    assert sleeps == [2.0, 4.0, 8.0]


def test_failing_ticker_does_not_stop_the_run(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df_aaa = make_bars([10.0, 11.0])

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {"AAA": df_aaa}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA", "BBB"], store, fetch, sleep, pause_s=0.0)

    assert report.succeeded == ["AAA"]
    assert report.failed == {"BBB": "keine Daten"}
    assert report.exit_code() == 0


def test_whole_batch_raises(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df_bbb = make_bars([10.0, 11.0])
    calls: list[list[str]] = []

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        calls.append(list(tickers))
        if tickers == ["AAA"]:
            raise RuntimeError("rate limited")
        return {"BBB": df_bbb}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA", "BBB"], store, fetch, sleep, pause_s=0.0, batch_size=1)

    assert "rate limited" in report.failed["AAA"]
    assert report.succeeded == ["BBB"]


def test_all_failed_exit_1(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA"], store, fetch, sleep, pause_s=0.0)
    assert report.exit_code() == 1


def test_all_skipped_exit_0(tmp_path: Path) -> None:
    store = write_store(tmp_path, {"AAA": make_bars([10.0])})

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        raise AssertionError("should not be called")

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA"], store, fetch, sleep, pause_s=0.0)
    assert report.skipped == ["AAA"]
    assert report.exit_code() == 0


def test_empty_batch_is_retried(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {}

    sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA"], store, fetch, sleep, pause_s=0.0)
    assert sleeps == [2.0, 4.0, 8.0]
    assert report.failed == {"AAA": "keine Daten"}


def test_pause_between_batches(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df = make_bars([10.0])

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {t: df for t in tickers}

    sleeps, sleep = _sleep_recorder()
    data_sync.download(["AAA", "BBB", "CCC"], store, fetch, sleep, pause_s=1.5, batch_size=1)
    assert sleeps == [1.5, 1.5]


def test_restart_skips_complete_tickers(tmp_path: Path) -> None:
    store = write_store(tmp_path, {"AAA": make_bars([10.0])})
    calls: list[list[str]] = []

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        calls.append(list(tickers))
        return {t: make_bars([10.0]) for t in tickers}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA", "BBB"], store, fetch, sleep, pause_s=0.0)
    assert calls == [["BBB"]]
    assert report.skipped == ["AAA"]


def test_update_appends_only_new_days(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0, 100.0, 100.0])  # D-3..D, close 100 at D
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1]

    calls: list[tuple[Sequence[str], date | None]] = []

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        calls.append((tickers, start))
        new = make_bars([100.0, 101.0, 102.0], start=last_date.date().isoformat())
        return {"AAA": new}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)

    result = store.read("AAA")
    assert len(result) == 6  # D-3..D + D+1, D+2
    assert calls[0][1] == last_date.date()
    assert report.succeeded == ["AAA"]


def test_reload_on_readjustment(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1].date()
    full_history = make_bars([50.0, 50.0])  # halved: 2:1 split

    calls: list[tuple[Sequence[str], date | None]] = []

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        calls.append((tickers, start))
        if start is None:
            return {"AAA": full_history}
        return {"AAA": make_bars([50.0], start=last_date.isoformat())}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)

    cleaned_full, _ = pd.DataFrame(), None
    from app.cleaning import clean_prices

    cleaned_full, _ = clean_prices(full_history)
    pd.testing.assert_frame_equal(store.read("AAA"), cleaned_full)
    assert report.reloaded == ["AAA"]
    assert calls[1] == (["AAA"], None)


def test_within_tolerance_appends_only(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1].date()
    calls: list[tuple[Sequence[str], date | None]] = []

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        calls.append((tickers, start))
        return {"AAA": make_bars([100.4], start=last_date.isoformat())}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)
    assert len(calls) == 1
    assert report.reloaded == []


def test_boundary_is_exclusive(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1].date()

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {"AAA": make_bars([100.5], start=last_date.isoformat())}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)
    assert report.reloaded == []


def test_reload_failure_leaves_file_unchanged(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    before = store.path("AAA").read_bytes()
    last_date = stored["date"].iloc[-1].date()

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        if start is None:
            raise RuntimeError("still limited")
        return {"AAA": make_bars([50.0], start=last_date.isoformat())}

    sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)

    assert "still limited" in report.failed["AAA"]
    assert store.path("AAA").read_bytes() == before
    assert sleeps == [2.0, 4.0, 8.0]


def test_no_overlap_row_appends(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1].date()
    next_day = pd.Timestamp(last_date) + pd.tseries.offsets.BDay(1)

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {"AAA": make_bars([101.0], start=next_day.date().isoformat())}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)
    assert len(store.read("AAA")) == 3
    assert report.reloaded == []


def test_render_lists_reloads(tmp_path: Path) -> None:
    stored = make_bars([100.0, 100.0])
    store = write_store(tmp_path, {"AAA": stored})
    last_date = stored["date"].iloc[-1].date()
    full_history = make_bars([50.0, 50.0])

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        if start is None:
            return {"AAA": full_history}
        return {"AAA": make_bars([50.0], start=last_date.isoformat())}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)
    rendered = report.render()
    assert "Neu geladen" in rendered
    assert "AAA" in rendered


def test_update_without_new_rows(tmp_path: Path) -> None:
    store = write_store(tmp_path, {"AAA": make_bars([100.0])})

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {}

    sleeps, sleep = _sleep_recorder()
    report = data_sync.update(store, fetch, sleep, pause_s=0.0)
    assert report.succeeded == ["AAA"]
    assert report.rows == 0
    assert sleeps == []


def test_report_counts(tmp_path: Path) -> None:
    store = PriceStore(tmp_path)
    df = make_bars([10.0, 11.0])

    def fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {"AAA": df}

    _sleeps, sleep = _sleep_recorder()
    report = data_sync.download(["AAA", "BBB"], store, fetch, sleep, pause_s=0.0)
    assert report.rows == len(df)
    rendered = report.render()
    assert "erfolgreich" in rendered
    assert "BBB" in rendered
