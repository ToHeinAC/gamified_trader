import pytest

from app.settings_rules import (
    ValidationError,
    validate_leverage,
    validate_name,
    validate_rate,
    validate_settings,
    validate_start_capital,
)


def test_name_trims() -> None:
    assert validate_name("  Anna  ", []) == "Anna"


@pytest.mark.parametrize("raw", ["", "   ", "a" * 41])
def test_name_length_error(raw: str) -> None:
    with pytest.raises(ValidationError, match="1\u201340 Zeichen"):
        validate_name(raw, [])


def test_name_duplicate_error() -> None:
    with pytest.raises(ValidationError, match="bereits vergeben"):
        validate_name("anna", ["Anna"])


def test_name_max_length_ok() -> None:
    assert validate_name("a" * 40, []) == "a" * 40


@pytest.mark.parametrize("value", [1000, 1_000_000, 10000.0])
def test_capital_ok(value: float) -> None:
    assert validate_start_capital(value) == int(value)


@pytest.mark.parametrize("value", [999, 1_000_001, 1500.5, None])
def test_capital_error(value: float | None) -> None:
    with pytest.raises(ValidationError, match="Startkapital"):
        validate_start_capital(value)


@pytest.mark.parametrize(("mid", "pro"), [(5, 10), (2, 2), (20, 20)])
def test_leverage_ok(mid: float, pro: float) -> None:
    assert validate_leverage(mid, pro) == (int(mid), int(pro))


@pytest.mark.parametrize(("mid", "pro"), [(1, 10), (5, 21), (12, 10), (5.5, 10)])
def test_leverage_error(mid: float, pro: float) -> None:
    with pytest.raises(ValidationError, match="Hebel"):
        validate_leverage(mid, pro)


@pytest.mark.parametrize(("value", "expected"), [(0.0, 0), (5.0, 50), (20.0, 200)])
def test_rate_ok(value: float, expected: int) -> None:
    assert validate_rate(value, 20.0, "msg") == expected


@pytest.mark.parametrize("value", [20.1, -0.1, 5.05, None])
def test_rate_error(value: float | None) -> None:
    with pytest.raises(ValidationError, match="msg"):
        validate_rate(value, 20.0, "msg")


def test_rate_fee_max() -> None:
    with pytest.raises(ValidationError):
        validate_rate(
            10.1, 10.0, "Gebührensatz muss zwischen 0,0 und 10,0 % liegen (Schritte 0,1)."
        )


def test_validate_settings_returns_user_settings() -> None:
    settings = validate_settings(20000, 5, 10, 5.0, 2.0)
    assert settings.start_capital_eur == 20000
    assert settings.lev_mid == 5
    assert settings.lev_pro == 10
    assert settings.interest_tenths == 50
    assert settings.fee_tenths == 20


def test_validate_settings_first_invalid_field_raises() -> None:
    with pytest.raises(ValidationError, match="Startkapital"):
        validate_settings(999, 5, 10, 5.0, 2.0)
