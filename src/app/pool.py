"""Snapshot pool: candidate selection, rows and report (PRD M4). Pure core, injected I/O."""

import bisect
import hashlib
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from app.eligibility import eligible_mask
from app.indicators import with_indicators
from app.signals import EVENTS, signal_flags
from app.trading import (
    DEFAULT_COSTS,
    HORIZONS,
    Costs,
    buy_option,
    label,
    make_cards,
    option_values,
    simulate_all,
)

LEVELS = (1, 5, 10)
REFERENCE_BALANCE = Decimal("10000.00")
SIGNAL_SHARE = 0.7
MIN_SPACING = 20

LoadFn = Callable[[str], pd.DataFrame]
_IntArray = np.ndarray[tuple[int], np.dtype[np.int64]]
_BoolArray = np.ndarray[tuple[int], np.dtype[np.bool_]]


class InsufficientSnapshotsError(ValueError):
    pass


@dataclass(frozen=True)
class TickerCandidates:
    ticker: str
    idx: _IntArray
    is_signal: _BoolArray


def ticker_candidates(ticker: str, bars: pd.DataFrame) -> TickerCandidates:
    ind = with_indicators(bars)
    mask = eligible_mask(ind)
    # numpy's own overload for flatnonzero is ambiguous under strict mode (verified in isolation,
    # same root cause as eligibility.py's np.cumsum/np.where).
    idx: _IntArray = np.flatnonzero(mask)  # pyright: ignore[reportUnknownMemberType]
    is_signal_day: _BoolArray = signal_flags(ind)["is_signal_day"].to_numpy()
    return TickerCandidates(ticker=ticker, idx=idx, is_signal=is_signal_day[idx])


def _flatten(
    cands: Sequence[TickerCandidates],
) -> tuple[list[str], _IntArray, _IntArray, _BoolArray]:
    ordered = sorted(cands, key=lambda c: c.ticker)
    tickers = [c.ticker for c in ordered]
    if not ordered:
        empty: _IntArray = np.array([], dtype=np.int64)
        return tickers, empty, empty, np.array([], dtype=np.bool_)
    # numpy's own overload for concatenate is ambiguous under strict mode (same root cause as
    # np.cumsum/np.flatnonzero above, verified in isolation).
    ticker_no: _IntArray = np.concatenate(  # pyright: ignore[reportUnknownMemberType]
        [np.full(len(c.idx), t, dtype=np.int64) for t, c in enumerate(ordered)]
    )
    idx_arr: _IntArray = np.concatenate(  # pyright: ignore[reportUnknownMemberType]
        [c.idx for c in ordered]
    )
    is_signal_arr: _BoolArray = np.concatenate(  # pyright: ignore[reportUnknownMemberType]
        [c.is_signal for c in ordered]
    )
    return tickers, ticker_no, idx_arr, is_signal_arr


@dataclass
class _SelectionState:
    ticker_no: _IntArray
    idx_arr: _IntArray
    is_signal_arr: _BoolArray
    order: _IntArray
    accepted_by_ticker: dict[int, list[int]]
    accepted_positions: set[int]


def _try_accept(state: _SelectionState, pos: int) -> bool:
    tno, i = int(state.ticker_no[pos]), int(state.idx_arr[pos])
    lst = state.accepted_by_ticker[tno]
    p = bisect.bisect_left(lst, i)
    if p > 0 and i - lst[p - 1] < MIN_SPACING:
        return False
    if p < len(lst) and lst[p] - i < MIN_SPACING:
        return False
    lst.insert(p, i)
    state.accepted_positions.add(pos)
    return True


def _accept_pass(state: _SelectionState, *, want_signal: bool, target: int, count: int) -> int:
    for raw_pos in state.order:
        if count >= target:
            break
        pos = int(raw_pos)
        if pos in state.accepted_positions or bool(state.is_signal_arr[pos]) != want_signal:
            continue
        if _try_accept(state, pos):
            count += 1
    return count


def select(
    cands: Sequence[TickerCandidates], n: int, seed: int
) -> tuple[list[tuple[str, int]], list[str]]:
    """Deterministic selection: signal days first (D6), non-signal fill the rest."""
    tickers, ticker_no, idx_arr, is_signal_arr = _flatten(cands)
    # numpy's own overload for permutation is ambiguous under strict mode (same root cause as the
    # other numpy calls in this module, verified in isolation).
    order: _IntArray = np.random.default_rng(seed).permutation(  # pyright: ignore[reportUnknownMemberType]
        len(idx_arr)
    )
    state = _SelectionState(ticker_no, idx_arr, is_signal_arr, order, defaultdict(list), set())
    notes: list[str] = []

    n_sig_target = round(SIGNAL_SHARE * n)
    sig_count = _accept_pass(state, want_signal=True, target=n_sig_target, count=0)
    if sig_count < n_sig_target:
        notes.append(f"Nur {sig_count} Signaltage verfügbar (Ziel {n_sig_target}).")

    other_count = _accept_pass(state, want_signal=False, target=n - sig_count, count=0)
    if sig_count + other_count < n:
        sig_count = _accept_pass(state, want_signal=True, target=n - other_count, count=sig_count)

    total = sig_count + other_count
    if total < n:
        raise InsufficientSnapshotsError(f"benötigt {n}, verfügbar {total}")

    positions = sorted(state.accepted_positions)
    selection = [(tickers[int(ticker_no[pos])], int(idx_arr[pos])) for pos in positions]
    return selection, notes


def snapshot_id(ticker: str, t0: pd.Timestamp) -> str:
    return hashlib.sha1(f"{ticker}|{t0:%Y-%m-%d}".encode()).hexdigest()[:12]


def _card_columns(row: dict[str, object], ind: pd.DataFrame, i: int) -> None:
    p0 = float(ind["close"].iloc[i])
    atr = float(ind["atr14"].iloc[i])
    future = (
        ind[["open", "high", "low", "close"]].iloc[i + 1 : i + 1 + HORIZONS[-1]].to_numpy().tolist()
    )
    for leverage in LEVELS:
        cards = make_cards(p0, atr, REFERENCE_BALANCE, leverage, DEFAULT_COSTS)
        results = simulate_all(cards, future)
        values = option_values(results, REFERENCE_BALANCE)
        for horizon in HORIZONS:
            result = results[horizon]
            row[f"v_l{leverage}_h{horizon}"] = values[buy_option(horizon)]
            row[f"exit_l{leverage}_h{horizon}"] = result.reason.value
            row[f"exit_day_l{leverage}_h{horizon}"] = result.exit_day
        row[f"label_l{leverage}"] = label(values)


def snapshot_row(ticker: str, ind: pd.DataFrame, flags: pd.DataFrame, i: int) -> dict[str, object]:
    t0 = pd.Timestamp(ind["date"].iloc[i])
    row: dict[str, object] = {
        "snapshot_id": snapshot_id(ticker, t0),
        "ticker": ticker,
        "t0": t0,
        "n_hist": i + 1,
    }
    for event in EVENTS:
        row[f"sig_{event}"] = bool(flags[f"sig_{event}"].iloc[i])
    row["is_signal_day"] = bool(flags["is_signal_day"].iloc[i])
    _card_columns(row, ind, i)
    return row


def _apply_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    df["snapshot_id"] = df["snapshot_id"].astype(str)
    df["ticker"] = df["ticker"].astype(str)
    df["t0"] = df["t0"].astype("datetime64[ns]")
    df["n_hist"] = df["n_hist"].astype("int64")
    for event in EVENTS:
        df[f"sig_{event}"] = df[f"sig_{event}"].astype(bool)
    df["is_signal_day"] = df["is_signal_day"].astype(bool)
    for leverage in LEVELS:
        for horizon in HORIZONS:
            df[f"v_l{leverage}_h{horizon}"] = df[f"v_l{leverage}_h{horizon}"].astype("float64")
            df[f"exit_l{leverage}_h{horizon}"] = df[f"exit_l{leverage}_h{horizon}"].astype(str)
            df[f"exit_day_l{leverage}_h{horizon}"] = df[f"exit_day_l{leverage}_h{horizon}"].astype(
                "int64"
            )
        df[f"label_l{leverage}"] = df[f"label_l{leverage}"].astype(str)
    return df


def _costs_dict(costs: Costs) -> tuple[float, float]:
    return float(costs.fee_rate), float(costs.interest_rate)


def _build_report(
    df: pd.DataFrame,
    n: int,
    seed: int,
    data_as_of: pd.Timestamp | None,
    n_tickers: int,
    notes: list[str],
    tickers_without_snapshots: list[str],
) -> dict[str, object]:
    fee_rate, interest_rate = _costs_dict(DEFAULT_COSTS)
    label_counts = {
        f"l{leverage}": {str(k): int(v) for k, v in df[f"label_l{leverage}"].value_counts().items()}
        for leverage in LEVELS
    }
    period = [
        df["t0"].min().strftime("%Y-%m-%d") if len(df) else None,
        df["t0"].max().strftime("%Y-%m-%d") if len(df) else None,
    ]
    return {
        "n": n,
        "seed": seed,
        "data_as_of": data_as_of.strftime("%Y-%m-%d") if data_as_of is not None else None,
        "fee_rate": fee_rate,
        "interest_rate": interest_rate,
        "levels": list(LEVELS),
        "reference_balance": float(REFERENCE_BALANCE),
        "signal_share": float(df["is_signal_day"].mean()) if len(df) else 0.0,
        "n_tickers": n_tickers,
        "period": period,
        "label_counts": label_counts,
        "tickers_without_snapshots": tickers_without_snapshots,
        "notes": notes,
    }


def _gather_candidates(
    tickers: Sequence[str], load: LoadFn
) -> tuple[list[TickerCandidates], list[str], pd.Timestamp | None]:
    candidates: list[TickerCandidates] = []
    without: list[str] = []
    data_as_of: pd.Timestamp | None = None
    for ticker in sorted(tickers):
        bars = load(ticker)
        if bars.empty:
            without.append(ticker)
            continue
        ticker_max = pd.Timestamp(bars["date"].iloc[-1])
        data_as_of = ticker_max if data_as_of is None else max(data_as_of, ticker_max)
        cand = ticker_candidates(ticker, bars)
        if len(cand.idx) == 0:
            without.append(ticker)
            continue
        candidates.append(cand)
    return candidates, without, data_as_of


def build_pool(
    tickers: Sequence[str], load: LoadFn, n: int, seed: int
) -> tuple[pd.DataFrame, dict[str, object]]:
    candidates, without, data_as_of = _gather_candidates(tickers, load)
    selection, notes = select(candidates, n, seed)

    by_ticker: dict[str, list[int]] = defaultdict(list)
    for ticker, idx in selection:
        by_ticker[ticker].append(idx)

    for cand in candidates:
        if cand.ticker not in by_ticker:
            without.append(cand.ticker)

    rows: list[dict[str, object]] = []
    for ticker in sorted(by_ticker):
        bars = load(ticker)
        ind = with_indicators(bars)
        flags = signal_flags(ind)
        for idx in sorted(by_ticker[ticker]):
            rows.append(snapshot_row(ticker, ind, flags, idx))

    df = _apply_dtypes(pd.DataFrame(rows)).sort_values(["ticker", "t0"]).reset_index(drop=True)
    report = _build_report(df, n, seed, data_as_of, len(tickers), notes, sorted(set(without)))
    return df, report
