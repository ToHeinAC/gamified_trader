from decimal import Decimal

import pytest

from app.trading import (
    OptionCode,
    book,
    k_locked,
    label,
    option_values,
    points,
    value_balance,
)


def test_example_points() -> None:
    values = {
        OptionCode.K10: 0.012,
        OptionCode.K30: -0.010,
        OptionCode.K120: 0.020,
        OptionCode.W10: -0.012,
        OptionCode.W30: 0.010,
        OptionCode.W120: -0.020,
    }
    result = points(values)
    assert result[OptionCode.K120] == 100
    assert result[OptionCode.K10] == 60
    assert result[OptionCode.W30] == 50
    for option in (OptionCode.K30, OptionCode.W10, OptionCode.W120):
        assert result[option] == 0


def test_multiple_optima() -> None:
    values = {OptionCode.K10: 0.02, OptionCode.K30: 0.02 - 0.00005}
    result = points(values)
    assert result[OptionCode.K10] == 100
    assert result[OptionCode.K30] == 100


def test_neutral() -> None:
    values = {OptionCode.K10: 0.00005, OptionCode.W10: -0.00005}
    assert points(values) == {OptionCode.K10: 0, OptionCode.W10: 0}
    assert label(values) == "NEUTRAL"
    from app.trading import optimal_options

    assert optimal_options(values) == []


def test_label_tie_break() -> None:
    values = {OptionCode.K30: 0.02, OptionCode.W10: 0.02}
    assert label(values) == "K30"


def test_cap_99() -> None:
    values = {OptionCode.K10: 0.02, OptionCode.K30: 0.02 - 0.0002}
    result = points(values)
    assert result[OptionCode.K30] == 99


def test_booking() -> None:
    balance = Decimal("10000.00")
    assert book(balance, OptionCode.W10, Decimal("500.00")) == balance
    assert book(balance, OptionCode.K10, Decimal("500.00")) == Decimal("10500.00")


def test_lock() -> None:
    start = Decimal("10000.00")
    assert k_locked(Decimal("0"), start) is True
    assert k_locked(Decimal("99.99"), start) is True
    assert k_locked(Decimal("100.00"), start) is False
    assert value_balance(Decimal("0"), start) == start


def test_option_values_on_zero_balance() -> None:
    from app.trading import ExitReason, TradeResult

    result = TradeResult(
        entry=Decimal("100"),
        sl=Decimal("95"),
        tp=Decimal("110"),
        ko=None,
        exit_price=Decimal("100"),
        reason=ExitReason.TIME,
        exit_day=30,
        ret=Decimal("0"),
        fee=Decimal("0"),
        financing=Decimal("0"),
        pnl=Decimal("0"),
    )
    with pytest.raises(ValueError, match="balance"):
        option_values({30: result}, Decimal("0"))
