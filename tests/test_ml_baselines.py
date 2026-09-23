"""Tests for app.ml baselines and per-row evaluation (PRD R14)."""

import numpy as np
import pandas as pd
import pytest

from app.ml import (
    Recommendation,
    baseline_always_k120,
    baseline_most_frequent_label,
    baseline_random,
    option_value_l1,
    option_values_at_level,
    realized_value,
    recommendation_points,
)
from app.trading import Level, OptionCode, points


def _row(v_l1_h10: float, v_l1_h30: float, v_l1_h120: float, label_l1: str) -> pd.Series:
    return pd.Series(
        {
            "v_l1_h10": v_l1_h10,
            "v_l1_h30": v_l1_h30,
            "v_l1_h120": v_l1_h120,
            "v_l5_h10": v_l1_h10 * 5,
            "v_l5_h30": v_l1_h30 * 5,
            "v_l5_h120": v_l1_h120 * 5,
            "label_l1": label_l1,
        }
    )


def _pool_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(0.01, -0.02, 0.05, "K120"),
            _row(-0.01, 0.02, -0.05, "K30"),
            _row(0.03, 0.01, -0.01, "K120"),
            _row(-0.02, -0.01, 0.00, "NEUTRAL"),
        ]
    )


def test_baseline_always_k120() -> None:
    df = _pool_df()
    mask = np.array([True, True, True, True])
    result = baseline_always_k120(df, mask)
    assert result == pytest.approx((0.05 - 0.05 - 0.01 + 0.00) / 4)


def test_baseline_most_frequent_label_excludes_neutral() -> None:
    df = _pool_df()
    train_mask = np.array([True, True, True, True])
    test_mask = np.array([True, True, True, True])
    result = baseline_most_frequent_label(df[train_mask], df[test_mask])
    # K120 is the most frequent non-neutral label -> mean of v_l1_h120 over the test rows
    expected = df["v_l1_h120"].mean()
    assert result == pytest.approx(expected)


def test_baseline_most_frequent_label_all_neutral() -> None:
    df = pd.DataFrame([_row(0.0, 0.0, 0.0, "NEUTRAL")])
    mask = np.array([True])
    assert baseline_most_frequent_label(df[mask], df[mask]) == 0.0


def test_baseline_random_is_deterministic_and_uses_level_1() -> None:
    df = _pool_df()
    mask = np.array([True, True, True, True])
    a = baseline_random(df, mask, seed=7)
    b = baseline_random(df, mask, seed=7)
    c = baseline_random(df, mask, seed=8)
    assert a == b
    assert a != c


def test_option_value_l1_mirrors_wait() -> None:
    row = _row(0.02, -0.01, 0.03, "K10")
    assert option_value_l1(row, OptionCode.K10) == pytest.approx(0.02)
    assert option_value_l1(row, OptionCode.W10) == pytest.approx(-0.02)


def test_option_values_at_level_matches_stored_columns() -> None:
    row = _row(0.02, -0.01, 0.03, "K10")
    values = option_values_at_level(row, 5)
    assert values[OptionCode.K10] == pytest.approx(0.10)
    assert values[OptionCode.W10] == pytest.approx(-0.10)


def test_realized_value_for_buy_and_wait() -> None:
    row = _row(0.02, -0.01, 0.03, "K10")
    buy = Recommendation(OptionCode.K30, Level.MITTEL, 0.0, 0.0, 0.0)
    wait = Recommendation(OptionCode.W120, Level.EINFACH, 0.0, 0.0, 0.0)
    assert realized_value(row, buy) == pytest.approx(-0.01 * 5)
    assert realized_value(row, wait) == pytest.approx(-0.03)


def test_recommendation_points_matches_trading_points() -> None:
    row = _row(0.02, -0.01, 0.05, "K120")
    rec = Recommendation(OptionCode.K120, Level.EINFACH, 0.0, 0.0, 0.0)
    values = option_values_at_level(row, 1)
    assert recommendation_points(row, rec) == points(values)[OptionCode.K120]
