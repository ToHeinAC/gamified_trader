from decimal import Decimal

from app.trading import (
    DEFAULT_COSTS,
    Level,
    OptionCode,
    distance,
    fee,
    financing,
    leverage_for,
    make_card,
    make_cards,
    stake,
    stop_levels,
)

P0 = 100.0
ATR = 2.0
BALANCE = Decimal("10000.00")


def test_example_table() -> None:
    cards = make_cards(P0, ATR, BALANCE, 1, DEFAULT_COSTS)

    k10 = cards[OptionCode.K10]
    assert k10.d == Decimal("0.0300")
    assert k10.sl_price == Decimal("97.00")
    assert k10.tp_price == Decimal("106.00")
    assert k10.f == Decimal(1) / Decimal(3)
    assert k10.stake == Decimal("3333.33")
    assert k10.fee == Decimal("66.67")

    k30 = cards[OptionCode.K30]
    assert k30.d == Decimal("0.0500")
    assert k30.sl_price == Decimal("95.00")
    assert k30.tp_price == Decimal("110.00")
    assert k30.f == Decimal("0.2")
    assert k30.stake == Decimal("2000.00")
    assert k30.fee == Decimal("40.00")

    k120 = cards[OptionCode.K120]
    assert k120.d == Decimal("0.0800")
    assert k120.sl_price == Decimal("92.00")
    assert k120.tp_price == Decimal("116.00")
    assert k120.f == Decimal("0.125")
    assert k120.stake == Decimal("1250.00")
    assert k120.fee == Decimal("25.00")


def test_card_k30_einfach() -> None:
    card = make_card(30, P0, ATR, BALANCE, 1, DEFAULT_COSTS)
    assert card.exposure == Decimal("2000.00")
    assert card.qty == Decimal(20)
    assert card.loss_at_sl == Decimal("140.00")
    assert card.gain_at_tp == Decimal("160.00")
    assert card.financing_full == Decimal("0.00")
    assert card.ko_price is None


def test_card_k30_profi() -> None:
    card = make_card(30, P0, ATR, BALANCE, 10, DEFAULT_COSTS)
    assert card.exposure == Decimal("20000.00")
    assert card.qty == Decimal(200)
    assert card.loss_at_sl == Decimal("1040.00")
    assert card.gain_at_tp == Decimal("1960.00")
    assert card.financing_full == Decimal("107.14")
    assert card.ko_distance == Decimal("-0.1")


def test_k120_profi_clamp_edge() -> None:
    card = make_card(120, P0, 10.0, BALANCE, 10, DEFAULT_COSTS)
    assert card.d == Decimal("0.0800")


def test_gap_entry() -> None:
    sl, tp, _ko = stop_levels(Decimal("103.00"), Decimal("0.05"), 1)
    assert sl == Decimal("97.85")
    assert tp == Decimal("113.30")

    card = make_card(30, P0, ATR, BALANCE, 1, DEFAULT_COSTS)
    assert card.stake == Decimal("2000.00")


def test_clamp_low() -> None:
    d = distance(10, 0.01, P0, 1)
    assert d == Decimal("0.0100")
    f, m = stake(d, BALANCE)
    assert f == Decimal(1)
    assert m == BALANCE


def test_clamp_high() -> None:
    d = distance(30, 10.0, P0, 10)
    assert d == Decimal("0.0800")
    card = make_card(30, P0, 10.0, BALANCE, 10, DEFAULT_COSTS)
    assert card.tp_price == Decimal("116.00")


def test_fee_identical_across_leverage() -> None:
    fees = {
        leverage: make_card(30, P0, ATR, BALANCE, leverage, DEFAULT_COSTS).fee
        for leverage in (1, 5, 10)
    }
    assert len(set(fees.values())) == 1


def test_leverage_for() -> None:
    assert leverage_for(Level.EINFACH, 5, 10) == 1
    assert leverage_for(Level.MITTEL, 5, 10) == 5
    assert leverage_for(Level.PROFI, 5, 10) == 10


def test_fee_and_financing_helpers() -> None:
    assert fee(Decimal("2000.00"), DEFAULT_COSTS) == Decimal("40.00")
    assert financing(Decimal("2000.00"), 1, DEFAULT_COSTS, 30) == Decimal("0.00")
    assert financing(Decimal("2000.00"), 10, DEFAULT_COSTS, 30) == Decimal("107.14")
