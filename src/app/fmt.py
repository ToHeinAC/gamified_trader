"""German number and money formatting (pure)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd


def _swap(s: str) -> str:
    return s.replace(",", "￾").replace(".", ",").replace("￾", ".")


def eur(amount: Decimal) -> str:
    return f"{_swap(f'{amount:,.2f}')} €"


def cents_eur(cents: int) -> str:
    return eur(Decimal(cents) / 100)


def pct(v: float, signed: bool = True) -> str:
    formatted = _swap(f"{v * 100:,.2f}")
    if signed and v > 0:
        formatted = f"+{formatted}"
    return f"{formatted} %"


def price(x: Decimal) -> str:
    return _swap(f"{x:,.2f}")


def qty(x: Decimal) -> str:
    if x >= 1:
        rounded = int(x.to_integral_value(rounding=ROUND_HALF_UP))
        return f"≈ {points(rounded)}"
    return f"≈ {_swap(f'{x:.1f}')}"


def date_de(d: date | pd.Timestamp) -> str:
    return d.strftime("%d.%m.%Y")


def points(n: int) -> str:
    return f"{n:,}".replace(",", ".")
