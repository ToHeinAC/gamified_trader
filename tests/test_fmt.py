from datetime import date
from decimal import Decimal

from app.fmt import cents_eur, date_de, eur, pct, points, price, qty


def test_eur() -> None:
    assert eur(Decimal("10000")) == "10.000,00 €"
    assert eur(Decimal("-1247.14")) == "-1.247,14 €"


def test_cents_eur() -> None:
    assert cents_eur(1_000_000) == "10.000,00 €"


def test_pct() -> None:
    assert pct(0.016) == "+1,60 %"
    assert pct(-0.124714) == "-12,47 %"
    assert pct(0) == "0,00 %"


def test_price() -> None:
    assert price(Decimal("97.85")) == "97,85"


def test_qty() -> None:
    assert qty(Decimal(20)) == "≈ 20"
    assert qty(Decimal("0.5")) == "≈ 0,5"


def test_date_de() -> None:
    assert date_de(date(2024, 12, 31)) == "31.12.2024"


def test_points() -> None:
    assert points(1240) == "1.240"
