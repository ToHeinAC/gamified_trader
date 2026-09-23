"""Pure game logic: draw, settings, card text, resolution (PRD M6). No I/O."""

import random
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.db import RoundRow, UserRow
from app.fmt import eur, pct, price, qty
from app.trading import (
    OPTIONS,
    Card,
    Costs,
    ExitReason,
    Level,
    OptionCode,
    TradeResult,
    book,
    dec,
    horizon_of,
    is_buy,
    is_neutral,
    k_locked,
    leverage_for,
    make_cards,
    optimal_options,
    option_values,
    points,
    simulate_all,
    value_balance,
)


@dataclass(frozen=True)
class PoolEntry:
    snapshot_id: str
    ticker: str
    t0: date
    label: str


def draw_snapshot(
    entries: Sequence[PoolEntry],
    play_counts: Mapping[str, int],
    rng: random.Random,
    exclude: AbstractSet[str] = frozenset(),
) -> PoolEntry | None:
    """Among non-excluded entries with the minimum play count: choose a label uniformly among
    the labels present (sorted for determinism), then an entry uniformly within that label."""
    candidates = [e for e in entries if e.snapshot_id not in exclude]
    if not candidates:
        return None
    min_count = min(play_counts.get(e.snapshot_id, 0) for e in candidates)
    pool = [e for e in candidates if play_counts.get(e.snapshot_id, 0) == min_count]
    labels = sorted({e.label for e in pool})
    label = rng.choice(labels)
    within_label = [e for e in pool if e.label == label]
    return rng.choice(within_label)


@dataclass(frozen=True)
class Setting:
    level: Level
    leverage: int
    costs: Costs
    balance: Decimal
    start_capital: Decimal


def costs_of(fee_tenths: int, interest_tenths: int) -> Costs:
    return Costs(Decimal(fee_tenths) / 1000, Decimal(interest_tenths) / 1000)


def setting_for(user: UserRow, level: Level) -> Setting:
    return Setting(
        level=level,
        leverage=leverage_for(level, user.lev_mid, user.lev_pro),
        costs=costs_of(user.fee_tenths, user.interest_tenths),
        balance=Decimal(user.balance_cents) / 100,
        start_capital=Decimal(user.start_capital_cents) / 100,
    )


def setting_of_round(rnd: RoundRow, start_capital_cents: int) -> Setting:
    assert rnd.level is not None
    assert rnd.leverage is not None
    assert rnd.fee_tenths is not None
    assert rnd.interest_tenths is not None
    assert rnd.balance_before_cents is not None
    return Setting(
        level=Level(rnd.level),
        leverage=rnd.leverage,
        costs=costs_of(rnd.fee_tenths, rnd.interest_tenths),
        balance=Decimal(rnd.balance_before_cents) / 100,
        start_capital=Decimal(start_capital_cents) / 100,
    )


@dataclass(frozen=True)
class SnapshotBars:
    p0: float
    atr: float
    future: list[list[float]]


def decision_cards(snap: SnapshotBars, s: Setting) -> dict[OptionCode, Card]:
    return make_cards(snap.p0, snap.atr, s.balance, s.leverage, s.costs)


def _card_line1(card: Card, s: Setting) -> str:
    return f"{card.option.value} · {card.horizon} Tage · {s.level.value}"


def _card_line2(card: Card) -> str:
    return (
        f"SL {pct(-float(card.d))} → {price(card.sl_price)} · "
        f"TP {pct(float(card.d) * 2)} → {price(card.tp_price)} · CRV 1 : 2"
    )


def _card_line3(card: Card) -> str:
    return (
        f"Einsatz {eur(card.stake)} ({pct(float(card.f), signed=False)} von B) · "
        f"Hebel {card.leverage} · Exposure {eur(card.exposure)}"
    )


def _card_line5(card: Card) -> str:
    ko_pct = pct(float(card.ko_distance), signed=False) if card.ko_distance is not None else ""
    return f"Finanzierung ({card.horizon} Tage) {eur(card.financing_full)} · KO-Abstand {ko_pct}"


def card_lines(card: Card, s: Setting) -> list[str]:
    lines = [
        _card_line1(card, s),
        _card_line2(card),
        _card_line3(card),
        f"Stückzahl {qty(card.qty)} · Gebühr {eur(card.fee)}",
    ]
    if card.leverage > 1:
        lines.append(_card_line5(card))
    lines.append(f"Verlust bei SL {eur(card.loss_at_sl)} · Gewinn bei TP {eur(card.gain_at_tp)}")
    return lines


def wait_lines(horizon: int) -> list[str]:
    return [f"Warten {horizon} Tage", "Kein Einsatz, keine Kosten"]


@dataclass(frozen=True)
class OptionOutcome:
    option: OptionCode
    value: float
    amount: Decimal
    reason: ExitReason | None
    costs: Decimal
    points: int
    optimal: bool


@dataclass(frozen=True)
class Resolution:
    setting: Setting
    chosen: OptionCode
    neutral: bool
    outcomes: dict[OptionCode, OptionOutcome]
    results: dict[int, TradeResult]
    pnl: Decimal
    fee: Decimal
    financing: Decimal
    balance_after: Decimal


def _outcomes(
    results: Mapping[int, TradeResult], values: Mapping[OptionCode, float], ref: Decimal
) -> dict[OptionCode, OptionOutcome]:
    optimal_set = set(optimal_options(values))
    pts = points(values)
    outcomes: dict[OptionCode, OptionOutcome] = {}
    for option in OPTIONS:
        result = results[horizon_of(option)]
        reason = result.reason if is_buy(option) else None
        costs = (result.fee + result.financing) if is_buy(option) else Decimal(0)
        value = values[option]
        outcomes[option] = OptionOutcome(
            option=option,
            value=value,
            amount=dec(value) * ref,
            reason=reason,
            costs=costs,
            points=pts[option],
            optimal=option in optimal_set,
        )
    return outcomes


def resolve(snap: SnapshotBars, s: Setting, chosen: OptionCode) -> Resolution:
    ref = value_balance(s.balance, s.start_capital)
    if is_buy(chosen) and k_locked(s.balance, s.start_capital):
        raise ValueError("Kaufoptionen gesperrt: Guthaben unter 1 % des Startkapitals")

    cards = make_cards(snap.p0, snap.atr, ref, s.leverage, s.costs)
    results = simulate_all(cards, snap.future)
    values = option_values(results, ref)
    outcomes = _outcomes(results, values, ref)

    if is_buy(chosen):
        chosen_result = results[horizon_of(chosen)]
        pnl, fee, financing = chosen_result.pnl, chosen_result.fee, chosen_result.financing
    else:
        pnl = fee = financing = Decimal(0)

    return Resolution(
        setting=s,
        chosen=chosen,
        neutral=is_neutral(values),
        outcomes=outcomes,
        results=results,
        pnl=pnl,
        fee=fee,
        financing=financing,
        balance_after=book(s.balance, chosen, pnl),
    )


@dataclass(frozen=True)
class RoundOutcome:
    level: str
    leverage: int
    fee_tenths: int
    interest_tenths: int
    option: str
    v: float
    pnl_cents: int
    fee_cents: int
    financing_cents: int
    points: int
    balance_after_cents: int


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def outcome(res: Resolution, fee_tenths: int, interest_tenths: int) -> RoundOutcome:
    chosen_outcome = res.outcomes[res.chosen]
    return RoundOutcome(
        level=res.setting.level.value,
        leverage=res.setting.leverage,
        fee_tenths=fee_tenths,
        interest_tenths=interest_tenths,
        option=res.chosen.value,
        v=chosen_outcome.value,
        pnl_cents=_to_cents(res.pnl),
        fee_cents=_to_cents(res.fee),
        financing_cents=_to_cents(res.financing),
        points=chosen_outcome.points,
        balance_after_cents=_to_cents(res.balance_after),
    )


def round_number(done_rounds: int, has_open: bool) -> int:
    return done_rounds + 1 if has_open else done_rounds


BadgeTier = Literal["optimal", "gut", "neutral", "schlecht"]


def badge_tier(*, neutral: bool, optimal: bool, points: int) -> BadgeTier:
    if neutral:
        return "neutral"
    if optimal:
        return "optimal"
    if points >= 50:
        return "gut"
    return "schlecht"
