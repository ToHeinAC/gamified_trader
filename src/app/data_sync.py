"""Download/update loop for Yahoo price data: retry, batching, reporting."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TypeVar

import pandas as pd

from app.cleaning import CleanStats, clean_prices
from app.price_store import PriceStore

FetchFn = Callable[[Sequence[str], date | None], dict[str, pd.DataFrame]]
SleepFn = Callable[[float], None]

BATCH_SIZE = 50
RETRIES = 3
BASE_DELAY_S = 2.0
READJUST_TOLERANCE = 0.005  # D13: relative change of the last stored close that forces a reload

T = TypeVar("T")


class EmptyBatchError(RuntimeError): ...


def call_with_retry(
    fn: Callable[[], T],
    sleep: SleepFn,
    retries: int = RETRIES,
    base_delay_s: float = BASE_DELAY_S,
) -> T:
    """Up to 1 + retries attempts; sleeps base * 2**k between them; re-raises the last error."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception:
            if attempt >= retries:
                raise
            sleep(base_delay_s * 2**attempt)
            attempt += 1


@dataclass
class SyncReport:
    mode: str
    succeeded: list[str] = field(default_factory=list[str])
    failed: dict[str, str] = field(default_factory=dict[str, str])
    skipped: list[str] = field(default_factory=list[str])
    reloaded: list[str] = field(default_factory=list[str])
    rows: int = 0
    corrections: int = 0
    dropped: int = 0

    def exit_code(self) -> int:
        return 1 if not self.succeeded and self.failed else 0

    def render(self) -> str:
        lines = [
            f"gt data {self.mode}: {len(self.succeeded)} erfolgreich, "
            f"{len(self.failed)} fehlgeschlagen, {len(self.skipped)} übersprungen",
            f"Zeilen: {self.rows} · Korrekturen: {self.corrections} · "
            f"entfernte Zeilen: {self.dropped}",
        ]
        if self.failed:
            lines.append("Fehlgeschlagen:")
            lines.extend(f"  {ticker}: {reason}" for ticker, reason in self.failed.items())
        if self.reloaded:
            lines.append(f"Neu geladen (Kursbereinigung geändert): {', '.join(self.reloaded)}")
        return "\n".join(lines)


def _batches(items: Sequence[str], batch_size: int) -> list[list[str]]:
    return [list(items[i : i + batch_size]) for i in range(0, len(items), batch_size)]


def _fetch_nonempty(
    fetch: FetchFn, batch: Sequence[str], start: date | None
) -> dict[str, pd.DataFrame]:
    frames = fetch(batch, start)
    if not frames:
        raise EmptyBatchError("empty batch")
    return frames


def _record_frame(
    store: PriceStore,
    ticker: str,
    frame: pd.DataFrame | None,
    report: SyncReport,
) -> None:
    if frame is None or frame.empty:
        report.failed[ticker] = "keine Daten"
        return
    cleaned, stats = clean_prices(frame)
    if cleaned.empty:
        report.failed[ticker] = "keine Daten"
        return
    store.write(ticker, cleaned)
    report.succeeded.append(ticker)
    report.rows += len(cleaned)
    report.corrections += stats.corrections
    report.dropped += stats.dropped_invalid + stats.dropped_duplicates


def download(
    tickers: Sequence[str],
    store: PriceStore,
    fetch: FetchFn,
    sleep: SleepFn,
    pause_s: float,
    batch_size: int = BATCH_SIZE,
) -> SyncReport:
    report = SyncReport(mode="download")
    todo = [t for t in tickers if not store.has(t)]
    report.skipped = [t for t in tickers if store.has(t)]

    batches = _batches(todo, batch_size)
    for i, batch in enumerate(batches):
        try:
            frames = call_with_retry(lambda b=batch: _fetch_nonempty(fetch, b, None), sleep)
        except EmptyBatchError:
            for t in batch:
                report.failed[t] = "keine Daten"
        except Exception as exc:
            for t in batch:
                report.failed[t] = repr(exc)
        else:
            for t in batch:
                _record_frame(store, t, frames.get(t), report)
        if i < len(batches) - 1:
            sleep(pause_s)
    return report


def _is_readjusted(store: PriceStore, ticker: str, cleaned: pd.DataFrame, last_date: date) -> bool:
    overlap = cleaned.loc[cleaned["date"] == pd.Timestamp(last_date)]
    if overlap.empty:
        return False
    stored_close = float(store.read(ticker)["close"].iloc[-1])
    new_close = float(overlap["close"].iloc[0])
    return abs(new_close / stored_close - 1) > READJUST_TOLERANCE


def _append_new_rows(
    store: PriceStore,
    ticker: str,
    cleaned: pd.DataFrame,
    last_date: date,
    report: SyncReport,
    stats: CleanStats,
) -> None:
    new_rows = cleaned.loc[cleaned["date"] > pd.Timestamp(last_date)]
    if not new_rows.empty:
        store.write(ticker, pd.concat([store.read(ticker), new_rows], ignore_index=True))
    report.succeeded.append(ticker)
    report.rows += len(new_rows)
    report.corrections += stats.corrections
    report.dropped += stats.dropped_invalid + stats.dropped_duplicates


def _reload(
    stale: Sequence[str], store: PriceStore, fetch: FetchFn, sleep: SleepFn, report: SyncReport
) -> None:
    try:
        frames = call_with_retry(lambda: _fetch_nonempty(fetch, stale, None), sleep)
    except EmptyBatchError:
        for t in stale:
            report.failed[t] = "keine Daten"
        return
    except Exception as exc:
        for t in stale:
            report.failed[t] = repr(exc)
        return
    for t in stale:
        frame = frames.get(t)
        if frame is None or frame.empty:
            report.failed[t] = "keine Daten"
            continue
        cleaned, stats = clean_prices(frame)
        store.write(t, cleaned)
        report.reloaded.append(t)
        report.succeeded.append(t)
        report.rows += len(cleaned)
        report.corrections += stats.corrections
        report.dropped += stats.dropped_invalid + stats.dropped_duplicates


def _update_batch(
    batch: Sequence[str], store: PriceStore, fetch: FetchFn, sleep: SleepFn, report: SyncReport
) -> None:
    last_dates = {t: store.last_date(t) for t in batch}
    start = min(d for d in last_dates.values() if d is not None)
    try:
        frames = call_with_retry(lambda: fetch(batch, start), sleep)
    except Exception as exc:
        for t in batch:
            report.failed[t] = repr(exc)
        return

    stale: list[str] = []
    for t in batch:
        frame = frames.get(t)
        if frame is None or frame.empty:
            report.succeeded.append(t)
            continue
        cleaned, stats = clean_prices(frame)
        last_date = last_dates[t]
        assert last_date is not None  # ticker came from store.tickers(), so it has a last date
        if _is_readjusted(store, t, cleaned, last_date):
            stale.append(t)
        else:
            _append_new_rows(store, t, cleaned, last_date, report, stats)

    if stale:
        _reload(stale, store, fetch, sleep, report)


def update(
    store: PriceStore,
    fetch: FetchFn,
    sleep: SleepFn,
    pause_s: float,
    batch_size: int = BATCH_SIZE,
) -> SyncReport:
    report = SyncReport(mode="update")
    batches = _batches(store.tickers(), batch_size)
    for i, batch in enumerate(batches):
        _update_batch(batch, store, fetch, sleep, report)
        if i < len(batches) - 1:
            sleep(pause_s)
    return report
