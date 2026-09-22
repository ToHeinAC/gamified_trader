import hashlib
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest

from app.eligibility import eligible_mask
from app.indicators import with_indicators
from app.pool import (
    InsufficientSnapshotsError,
    build_pool,
    snapshot_id,
    ticker_candidates,
)
from app.price_store import PriceStore
from app.signals import signal_flags
from app.trading import DEFAULT_COSTS, buy_option, label, make_cards, option_values, simulate_all
from tests.helpers import random_walk_bars, write_store

TICKERS = ["AAA", "BBB", "CCC", "DDD"]
REFERENCE_BALANCE = Decimal("10000.00")


def _frames(sigma: float = 0.02, n: int = 1600) -> dict[str, pd.DataFrame]:
    return {
        t: random_walk_bars(n, seed=i, sigma=sigma, start_price=50.0) for i, t in enumerate(TICKERS)
    }


def _store(tmp_path: Path, frames: dict[str, pd.DataFrame]) -> PriceStore:
    return write_store(tmp_path, frames)


def test_snapshot_id_shape() -> None:
    sid = snapshot_id("AAA", pd.Timestamp("2001-06-01"))
    assert len(sid) == 12
    assert sid == hashlib.sha1(b"AAA|2001-06-01").hexdigest()[:12]


def test_exactly_n_unique_ids(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    df, _report = build_pool(TICKERS, store.read, 120, seed=1)
    assert len(df) == 120
    assert df["snapshot_id"].nunique() == 120
    assert df["snapshot_id"].str.len().eq(12).all()


def test_every_row_eligible(tmp_path: Path) -> None:
    frames = _frames()
    store = _store(tmp_path, frames)
    df, _report = build_pool(TICKERS, store.read, 120, seed=1)
    for ticker in TICKERS:
        ind = with_indicators(frames[ticker])
        mask = eligible_mask(ind)
        rows = df[df["ticker"] == ticker]
        for t0 in rows["t0"]:
            i = int(ind.index[ind["date"] == t0][0])
            assert mask[i]


def test_spacing_within_ticker(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    df, _report = build_pool(TICKERS, store.read, 120, seed=1)
    for ticker in TICKERS:
        days = sorted(df[df["ticker"] == ticker]["t0"])
        for a, b in pairwise(days):
            assert (b - a).days >= 1


def test_signal_share_when_enough_exist(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames(sigma=0.03))
    df, report = build_pool(TICKERS, store.read, 100, seed=1)
    n_sig = round(0.7 * 100)
    assert int(df["is_signal_day"].sum()) == n_sig
    assert report["notes"] == []


def test_signal_shortage_uses_note_and_still_reaches_n(tmp_path: Path) -> None:
    from tests.helpers import make_bars

    flat = {t: make_bars([50.0] * 1600, spread=0.001) for t in TICKERS}
    store = _store(tmp_path, flat)
    df, report = build_pool(TICKERS, store.read, 100, seed=1)
    assert len(df) == 100
    assert not df["is_signal_day"].any()
    notes = cast(list[str], report["notes"])
    assert any("Signaltage" in note for note in notes)


def test_insufficient_raises(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    with pytest.raises(InsufficientSnapshotsError, match=r"benötigt.*verfügbar"):
        build_pool(TICKERS, store.read, 100_000, seed=1)


def test_determinism(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    df1, report1 = build_pool(TICKERS, store.read, 120, seed=7)
    df2, report2 = build_pool(TICKERS, store.read, 120, seed=7)
    pd.testing.assert_frame_equal(df1, df2)
    assert report1 == report2


def test_different_seed_gives_different_selection(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    df1, _report1 = build_pool(TICKERS, store.read, 120, seed=1)
    df2, _report2 = build_pool(TICKERS, store.read, 120, seed=2)
    assert set(df1["snapshot_id"]) != set(df2["snapshot_id"])


def test_causality_of_flags(tmp_path: Path) -> None:
    frames = _frames()
    store = _store(tmp_path, frames)
    df, _report = build_pool(TICKERS, store.read, 40, seed=3)
    for _, row in df.head(10).iterrows():
        bars = frames[str(row["ticker"])]
        t0_idx = int(bars.index[bars["date"] == row["t0"]][0])
        ind = with_indicators(bars.iloc[: t0_idx + 1])
        flags = signal_flags(ind)
        assert bool(flags["is_signal_day"].iloc[-1]) == bool(row["is_signal_day"])


def test_consistency_of_values(tmp_path: Path) -> None:
    frames = _frames()
    store = _store(tmp_path, frames)
    df, _report = build_pool(TICKERS, store.read, 40, seed=3)
    for _, row in df.head(10).iterrows():
        bars = frames[str(row["ticker"])]
        ind = with_indicators(bars)
        i = int(ind.index[ind["date"] == row["t0"]][0])
        future = ind[["open", "high", "low", "close"]].iloc[i + 1 : i + 121].to_numpy().tolist()
        for leverage in (1, 5, 10):
            cards = make_cards(
                float(ind["close"].iloc[i]),
                float(ind["atr14"].iloc[i]),
                REFERENCE_BALANCE,
                leverage,
                DEFAULT_COSTS,
            )
            results = simulate_all(cards, future)
            values = option_values(results, REFERENCE_BALANCE)
            for horizon in (10, 30, 120):
                assert row[f"v_l{leverage}_h{horizon}"] == pytest.approx(
                    values[buy_option(horizon)]
                )
                assert row[f"exit_l{leverage}_h{horizon}"] == results[horizon].reason.value
                assert row[f"exit_day_l{leverage}_h{horizon}"] == results[horizon].exit_day
            assert row[f"label_l{leverage}"] == label(values)


def test_report_fields(tmp_path: Path) -> None:
    store = _store(tmp_path, _frames())
    _df, report = build_pool(TICKERS, store.read, 120, seed=1)
    label_counts = cast(dict[str, dict[str, int]], report["label_counts"])
    period = cast(list[str], report["period"])
    for level in ("l1", "l5", "l10"):
        assert sum(label_counts[level].values()) == 120
    assert report["n_tickers"] == len(TICKERS)
    assert period[0] <= period[1]


def test_report_lists_ticker_with_too_little_history(tmp_path: Path) -> None:
    frames = _frames()
    frames["EEE"] = random_walk_bars(300, seed=99)
    store = _store(tmp_path, frames)
    _df, report = build_pool([*TICKERS, "EEE"], store.read, 120, seed=1)
    without = cast(list[str], report["tickers_without_snapshots"])
    assert "EEE" in without


def test_ticker_candidates_matches_eligible_mask() -> None:
    frames = _frames()
    bars = frames["AAA"]
    cand = ticker_candidates("AAA", bars)
    ind = with_indicators(bars)
    mask = eligible_mask(ind)
    assert np.array_equal(cand.idx, np.flatnonzero(mask))
