"""Setup input validation (pure). Messages are the exact German text shown in the UI."""

from collections.abc import Iterable
from dataclasses import dataclass

NAME_MAX = 40
CAPITAL_MIN, CAPITAL_MAX, CAPITAL_DEFAULT = 1_000, 1_000_000, 10_000
LEV_MIN, LEV_MAX = 2, 20
LEV_MID_DEFAULT, LEV_PRO_DEFAULT = 5, 10
INTEREST_MAX_PCT, FEE_MAX_PCT = 20.0, 10.0
INTEREST_DEFAULT_TENTHS, FEE_DEFAULT_TENTHS = 50, 20

_NAME_MSG = "Name muss 1\u201340 Zeichen lang sein."
_NAME_DUP_MSG = "Name ist bereits vergeben."
_CAPITAL_MSG = "Startkapital muss eine ganze Zahl von 1.000 bis 1.000.000 € sein."
_LEVERAGE_MSG = "Hebel müssen ganze Zahlen von 2 bis 20 sein, Mittel ≤ Profi."


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UserSettings:
    start_capital_eur: int
    lev_mid: int
    lev_pro: int
    interest_tenths: int
    fee_tenths: int


def name_key(name: str) -> str:
    return name.strip().casefold()


def validate_name(raw: str, existing: Iterable[str]) -> str:
    name = raw.strip()
    if not (1 <= len(name) <= NAME_MAX):
        raise ValidationError(_NAME_MSG)
    key = name_key(name)
    if any(name_key(other) == key for other in existing):
        raise ValidationError(_NAME_DUP_MSG)
    return name


def _is_integer(value: float | None) -> bool:
    return value is not None and float(value).is_integer()


def validate_start_capital(value: float | None) -> int:
    if value is None or not _is_integer(value) or not (CAPITAL_MIN <= value <= CAPITAL_MAX):
        raise ValidationError(_CAPITAL_MSG)
    return int(value)


def validate_leverage(mid: float | None, pro: float | None) -> tuple[int, int]:
    if mid is None or pro is None or not _is_integer(mid) or not _is_integer(pro):
        raise ValidationError(_LEVERAGE_MSG)
    mid_i, pro_i = int(mid), int(pro)
    if not (LEV_MIN <= mid_i <= LEV_MAX) or not (LEV_MIN <= pro_i <= LEV_MAX) or mid_i > pro_i:
        raise ValidationError(_LEVERAGE_MSG)
    return mid_i, pro_i


def validate_rate(value: float | None, max_pct: float, message: str) -> int:
    if value is None or not (0 <= value <= max_pct):
        raise ValidationError(message)
    tenths = round(value * 10)
    if abs(value * 10 - tenths) > 1e-9:
        raise ValidationError(message)
    return tenths


def validate_settings(
    capital: float | None,
    mid: float | None,
    pro: float | None,
    interest: float | None,
    fee: float | None,
) -> UserSettings:
    capital_eur = validate_start_capital(capital)
    lev_mid, lev_pro = validate_leverage(mid, pro)
    interest_tenths = validate_rate(
        interest, INTEREST_MAX_PCT, "Zinssatz muss zwischen 0,0 und 20,0 % liegen (Schritte 0,1)."
    )
    fee_tenths = validate_rate(
        fee, FEE_MAX_PCT, "Gebührensatz muss zwischen 0,0 und 10,0 % liegen (Schritte 0,1)."
    )
    return UserSettings(capital_eur, lev_mid, lev_pro, interest_tenths, fee_tenths)
