from decimal import Decimal

import pytest

from app.trading import (
    DEFAULT_COSTS,
    Card,
    ExitReason,
    OptionCode,
    financing,
    make_card,
    option_values,
    simulate,
)

P0 = 100.0
ATR = 2.0
BALANCE = Decimal("10000.00")
Q = (100.0, 100.5, 99.5, 100.0)


def future(
    *bars: tuple[float, float, float, float], total: int = 30
) -> list[tuple[float, float, float, float]]:
    rows = list(bars)
    while len(rows) < total:
        rows.append(Q)
    return rows


def card(leverage: int = 1) -> Card:
    return make_card(30, P0, ATR, BALANCE, leverage, DEFAULT_COSTS)


def test_tp_day2() -> None:
    result = simulate(card(), future(Q, (99.0, 111.0, 98.0, 100.0)))
    assert result.reason == ExitReason.TP
    assert result.exit_price == Decimal("110.00")
    assert result.exit_day == 2
    assert result.pnl == Decimal("160.00")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(0.016)


def test_sl_day1_no_gap_rule() -> None:
    result = simulate(card(), future((100.0, 100.0, 94.0, 95.0)))
    assert result.reason == ExitReason.SL
    assert result.exit_price == Decimal("95.00")
    assert result.exit_day == 1
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(-0.014)


def test_tp_day1_intraday() -> None:
    result = simulate(card(), future((100.0, 111.0, 99.0, 105.0)))
    assert result.reason == ExitReason.TP
    assert result.exit_price == Decimal("110.00")
    assert result.exit_day == 1


def test_gap_sl_day2() -> None:
    result = simulate(card(), future(Q, (94.0, 94.0, 94.0, 94.0)))
    assert result.reason == ExitReason.SL
    assert result.exit_price == Decimal("94.00")
    assert result.pnl == Decimal("-160.00")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(-0.016)


def test_gap_sl_day2_profi() -> None:
    result = simulate(card(10), future(Q, (94.0, 94.0, 94.0, 94.0)))
    assert result.financing == Decimal("7.14")
    assert result.pnl == Decimal("-1247.14")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(-0.124714)


def test_gap_under_ko_before_sl() -> None:
    result = simulate(card(10), future(Q, (89.0, 89.0, 89.0, 89.0)))
    assert result.reason == ExitReason.KO
    assert result.pnl == Decimal("-2000.00")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(-0.2)


def test_gap_tp_day2() -> None:
    result = simulate(card(), future(Q, (112.0, 113.0, 111.0, 112.0)))
    assert result.reason == ExitReason.TP
    assert result.exit_price == Decimal("112.00")


def test_sl_before_tp_same_day() -> None:
    result = simulate(card(), future(Q, (100.0, 111.0, 94.0, 100.0)))
    assert result.reason == ExitReason.SL
    assert result.exit_price == Decimal("95.00")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(-0.014)


def test_time_exit() -> None:
    bars = [Q] * 29 + [(100.0, 103.5, 99.5, 103.0)]
    result = simulate(card(), future(*bars))
    assert result.reason == ExitReason.TIME
    assert result.exit_day == 30
    assert result.exit_price == Decimal("103.00")
    assert result.pnl == Decimal("20.00")
    values = option_values({30: result}, BALANCE)
    assert values[OptionCode.K30] == pytest.approx(0.002)


def test_sl_equal_to_ko() -> None:
    from app.trading import exit_on_day

    result = exit_on_day(
        2, Decimal(89), Decimal(89), Decimal(89), Decimal(90), Decimal(200), Decimal(90)
    )
    assert result is not None
    assert result[1] == ExitReason.KO


def test_too_few_bars() -> None:
    with pytest.raises(ValueError, match="benötigt"):
        simulate(card(), future(*([Q] * 29), total=29))


def test_no_costs() -> None:
    from app.trading import Costs

    no_costs = Costs(Decimal("0"), Decimal("0"))
    c = make_card(30, P0, ATR, BALANCE, 1, no_costs)
    result = simulate(c, future(Q, (99.0, 111.0, 98.0, 100.0)))
    assert result.pnl == Decimal("200.00")


def test_financing_zero_at_leverage_one() -> None:
    assert financing(Decimal("2000"), 1, DEFAULT_COSTS, 30) == Decimal("0.00")


def test_financing_linear_in_days() -> None:
    values = {n: financing(Decimal("2000"), 10, DEFAULT_COSTS, n) for n in range(1, 31)}
    for n, value in values.items():
        expected = (Decimal(9) * Decimal(2000) * Decimal("0.05") * n / 252).quantize(
            Decimal("0.01")
        )
        assert abs(value - expected) <= Decimal("0.01")
    assert abs(values[20] - 2 * values[10]) <= Decimal("0.01")


def test_loss_floor() -> None:
    c = make_card(30, P0, ATR, BALANCE, 20, DEFAULT_COSTS)
    result = simulate(c, future(Q, (1.0, 1.0, 1.0, 1.0)))
    assert result.pnl == -c.stake
