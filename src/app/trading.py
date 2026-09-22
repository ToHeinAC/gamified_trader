"""Pure trading rules: cards, simulation and scoring (PRD R3-R9).

No pandas, no I/O. See docs/spec-m3-trading.md for the derivation of every formula.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum


class OptionCode(StrEnum):
    K10 = "K10"
    K30 = "K30"
    K120 = "K120"
    W10 = "W10"
    W30 = "W30"
    W120 = "W120"


OPTIONS = (
    OptionCode.K10,
    OptionCode.K30,
    OptionCode.K120,
    OptionCode.W10,
    OptionCode.W30,
    OptionCode.W120,
)
HORIZONS = (10, 30, 120)


class Level(StrEnum):
    EINFACH = "Einfach"
    MITTEL = "Mittel"
    PROFI = "Profi"


class ExitReason(StrEnum):
    TP = "TP"
    SL = "SL"
    KO = "KO"
    TIME = "TIME"


K_FACTOR = {10: Decimal("1.5"), 30: Decimal("2.5"), 120: Decimal("4.0")}
RISK = Decimal("0.01")
MIN_D = Decimal("0.01")
MAX_D_SIMPLE = Decimal("0.30")
KO_BUFFER = Decimal("0.8")
DAYS_PER_YEAR = 252
EPS = 0.0001
LOCK_SHARE = Decimal("0.01")
CENT = Decimal("0.01")
BP = Decimal("0.0001")


@dataclass(frozen=True)
class Costs:
    fee_rate: Decimal
    interest_rate: Decimal


DEFAULT_COSTS = Costs(Decimal("0.02"), Decimal("0.05"))


def dec(x: float) -> Decimal:
    return Decimal(repr(x))


def horizon_of(option: OptionCode) -> int:
    return int(option.value[1:])


def is_buy(option: OptionCode) -> bool:
    return option.value[0] == "K"


def buy_option(horizon: int) -> OptionCode:
    return OptionCode(f"K{horizon}")


def wait_option(horizon: int) -> OptionCode:
    return OptionCode(f"W{horizon}")


def leverage_for(level: Level, lev_mid: int, lev_pro: int) -> int:
    if level is Level.EINFACH:
        return 1
    if level is Level.MITTEL:
        return lev_mid
    return lev_pro


def _max_distance(leverage: int) -> Decimal:
    if leverage == 1:
        return MAX_D_SIMPLE
    return KO_BUFFER / leverage


def distance(horizon: int, atr: float, p0: float, leverage: int) -> Decimal:
    """clamp(k_H * A / P0, 1 %, d_max(L)), then quantize(BP, ROUND_HALF_UP) (D2)."""
    raw = K_FACTOR[horizon] * dec(atr) / dec(p0)
    clamped = min(max(raw, MIN_D), _max_distance(leverage))
    return clamped.quantize(BP, rounding=ROUND_HALF_UP)


def stake(d: Decimal, balance: Decimal) -> tuple[Decimal, Decimal]:
    """f = min(1, RISK / d); M = (f * balance) quantized to CENT with ROUND_FLOOR."""
    f = min(Decimal(1), RISK / d)
    m = (f * balance).quantize(CENT, rounding=ROUND_FLOOR)
    return f, m


def stop_levels(
    base: Decimal, d: Decimal, leverage: int
) -> tuple[Decimal, Decimal, Decimal | None]:
    """SL floor to CENT; TP ceiling to CENT; KO = base*(1 - 1/L) unrounded (D3)."""
    sl = (base * (1 - d)).quantize(CENT, rounding=ROUND_FLOOR)
    tp = (base * (1 + 2 * d)).quantize(CENT, rounding=ROUND_CEILING)
    ko = None if leverage == 1 else base * (1 - Decimal(1) / leverage)
    return sl, tp, ko


def fee(stake: Decimal, costs: Costs) -> Decimal:
    return (costs.fee_rate * stake).quantize(CENT, rounding=ROUND_HALF_UP)


def financing(stake: Decimal, leverage: int, costs: Costs, days: int) -> Decimal:
    if leverage == 1:
        return Decimal("0.00")
    raw = (leverage - 1) * stake * costs.interest_rate * days / DAYS_PER_YEAR
    return raw.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Card:
    option: OptionCode
    horizon: int
    leverage: int
    costs: Costs
    p0: Decimal
    d: Decimal
    f: Decimal
    stake: Decimal
    exposure: Decimal
    fee: Decimal
    sl_price: Decimal
    tp_price: Decimal
    ko_price: Decimal | None
    qty: Decimal
    financing_full: Decimal
    ko_distance: Decimal | None
    loss_at_sl: Decimal
    gain_at_tp: Decimal


def make_card(
    horizon: int, p0: float, atr: float, balance: Decimal, leverage: int, costs: Costs
) -> Card:
    p0_dec = dec(p0)
    d = distance(horizon, atr, p0, leverage)
    f, m = stake(d, balance)
    exposure = m * leverage
    fee_amount = fee(m, costs)
    sl, tp, ko = stop_levels(p0_dec, d, leverage)
    ko_distance = None if leverage == 1 else -Decimal(1) / leverage
    loss_at_sl = (m * leverage * d + fee_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    gain_at_tp = (m * leverage * 2 * d - fee_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    return Card(
        option=buy_option(horizon),
        horizon=horizon,
        leverage=leverage,
        costs=costs,
        p0=p0_dec,
        d=d,
        f=f,
        stake=m,
        exposure=exposure,
        fee=fee_amount,
        sl_price=sl,
        tp_price=tp,
        ko_price=ko,
        qty=exposure / p0_dec,
        financing_full=financing(m, leverage, costs, horizon),
        ko_distance=ko_distance,
        loss_at_sl=loss_at_sl,
        gain_at_tp=gain_at_tp,
    )


def make_cards(
    p0: float, atr: float, balance: Decimal, leverage: int, costs: Costs
) -> dict[OptionCode, Card]:
    return {buy_option(h): make_card(h, p0, atr, balance, leverage, costs) for h in HORIZONS}


@dataclass(frozen=True)
class TradeResult:
    entry: Decimal
    sl: Decimal
    tp: Decimal
    ko: Decimal | None
    exit_price: Decimal
    reason: ExitReason
    exit_day: int
    ret: Decimal
    fee: Decimal
    financing: Decimal
    pnl: Decimal


def _gap_exit(
    o: Decimal, sl: Decimal, tp: Decimal, ko: Decimal | None
) -> tuple[Decimal, ExitReason] | None:
    if ko is not None and o <= ko:
        return o, ExitReason.KO
    if o <= sl:
        return o, ExitReason.SL
    if o >= tp:
        return o, ExitReason.TP
    return None


def exit_on_day(
    day: int, o: Decimal, h: Decimal, lo: Decimal, sl: Decimal, tp: Decimal, ko: Decimal | None
) -> tuple[Decimal, ExitReason] | None:
    """R6 rows 1-5 in order; rows 1-3 (gaps) only for day >= 2."""
    if day >= 2:
        gap = _gap_exit(o, sl, tp, ko)
        if gap is not None:
            return gap
    if lo <= sl:
        return sl, ExitReason.SL
    if h >= tp:
        return tp, ExitReason.TP
    return None


def simulate(card: Card, future: Sequence[Sequence[float]]) -> TradeResult:
    """future[i] = (open, high, low, close) of day i+1 after Tag 0."""
    horizon = card.horizon
    if len(future) < horizon:
        raise ValueError(f"benötigt {horizon} Kerzen nach Tag 0, vorhanden {len(future)}")
    entry = dec(future[0][0])
    sl, tp, ko = stop_levels(entry, card.d, card.leverage)

    exit_price: Decimal | None = None
    reason = ExitReason.TIME
    exit_day = horizon
    for day in range(1, horizon + 1):
        o, h, lo, _c = (dec(x) for x in future[day - 1])
        hit = exit_on_day(day, o, h, lo, sl, tp, ko)
        if hit is not None:
            exit_price, reason = hit
            exit_day = day
            break
    if exit_price is None:
        exit_price = dec(future[horizon - 1][3])

    ret = exit_price / entry - 1
    financing_amount = financing(card.stake, card.leverage, card.costs, exit_day)
    raw_pnl = card.stake * card.leverage * ret - card.fee - financing_amount
    pnl = max(-card.stake, raw_pnl).quantize(CENT, rounding=ROUND_HALF_UP)
    return TradeResult(
        entry=entry,
        sl=sl,
        tp=tp,
        ko=ko,
        exit_price=exit_price,
        reason=reason,
        exit_day=exit_day,
        ret=ret,
        fee=card.fee,
        financing=financing_amount,
        pnl=pnl,
    )


def simulate_all(
    cards: Mapping[OptionCode, Card], future: Sequence[Sequence[float]]
) -> dict[int, TradeResult]:
    return {card.horizon: simulate(card, future) for card in cards.values()}


def option_values(results: Mapping[int, TradeResult], balance: Decimal) -> dict[OptionCode, float]:
    """V(K_H) = float(pnl / balance); V(W_H) = -V(K_H)."""
    if balance <= 0:
        raise ValueError("balance must be positive")
    values: dict[OptionCode, float] = {}
    for horizon, result in results.items():
        v = float(result.pnl / balance)
        values[buy_option(horizon)] = v
        values[wait_option(horizon)] = -v
    return values


def is_neutral(values: Mapping[OptionCode, float]) -> bool:
    return max(values.values()) < EPS


def optimal_options(values: Mapping[OptionCode, float]) -> list[OptionCode]:
    if is_neutral(values):
        return []
    best = max(values.values())
    return [o for o in OPTIONS if o in values and values[o] >= best - EPS]


def points(values: Mapping[OptionCode, float]) -> dict[OptionCode, int]:
    if is_neutral(values):
        return dict.fromkeys(values, 0)
    best = max(values.values())
    optimal = set(optimal_options(values))
    result: dict[OptionCode, int] = {}
    for o, v in values.items():
        if o in optimal:
            result[o] = 100
        elif v > 0:
            result[o] = min(99, math.floor(100 * v / best + 1e-9))
        else:
            result[o] = 0
    return result


def label(values: Mapping[OptionCode, float]) -> str:
    optimal = optimal_options(values)
    if not optimal:
        return "NEUTRAL"
    return optimal[0].value


def book(balance: Decimal, option: OptionCode, pnl: Decimal) -> Decimal:
    if is_buy(option):
        return balance + pnl
    return balance


def k_locked(balance: Decimal, start_capital: Decimal) -> bool:
    return balance < LOCK_SHARE * start_capital


def value_balance(balance: Decimal, start_capital: Decimal) -> Decimal:
    return start_capital if k_locked(balance, start_capital) else balance
