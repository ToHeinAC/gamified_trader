from decimal import Decimal

import numpy as np
import pytest

from app.trading import (
    DEFAULT_COSTS,
    EPS,
    HORIZONS,
    OptionCode,
    book,
    make_card,
    optimal_options,
    option_values,
    points,
    simulate,
    wait_option,
)

SEEDS = range(50)


def _future(rng: np.random.Generator, p0: float, n: int) -> list[tuple[float, float, float, float]]:
    bars: list[tuple[float, float, float, float]] = []
    prev_close = p0
    for _ in range(n):
        o = prev_close * float(np.exp(rng.normal(0, 0.03)))
        move = float(np.exp(rng.normal(0, 0.02)))
        close = o * move
        hi = max(o, close) * (1 + abs(float(rng.normal(0, 0.01))))
        lo = min(o, close) * (1 - abs(float(rng.normal(0, 0.01))))
        bars.append((o, hi, lo, close))
        prev_close = close
    return bars


@pytest.mark.parametrize("seed", SEEDS)
def test_property_invariants(seed: int) -> None:
    rng = np.random.default_rng(seed)
    leverage = int(rng.choice([1, 5, 10, 20]))
    atr = float(rng.uniform(0.1, 15))
    p0 = float(rng.uniform(5, 500))
    balance = Decimal(str(round(float(rng.uniform(100, 1_000_000)), 2)))
    future = _future(rng, p0, 120)

    results = {}
    for horizon in HORIZONS:
        card = make_card(horizon, p0, atr, balance, leverage, DEFAULT_COSTS)
        result = simulate(card, future)
        results[horizon] = result
        assert result.pnl >= -card.stake
        assert book(balance, card.option, result.pnl) >= 0

    values = option_values(results, balance)
    for horizon in HORIZONS:
        k = OptionCode(f"K{horizon}")
        w = wait_option(horizon)
        assert values[w] == -values[k]

    is_neutral = max(values.values()) < EPS
    if not is_neutral:
        best = max(values.values())
        pts = points(values)
        optimal = set(optimal_options(values))
        at_100 = {o for o, v in values.items() if v >= best - EPS}
        assert {o for o, p in pts.items() if p == 100} == at_100
        assert optimal == at_100
        for p in pts.values():
            assert 0 <= p <= 100
