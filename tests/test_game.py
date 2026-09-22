import random
from datetime import date
from decimal import Decimal

import pytest

from app.db import UserRow
from app.game import (
    PoolEntry,
    SnapshotBars,
    card_lines,
    draw_snapshot,
    resolve,
    setting_for,
    wait_lines,
)
from app.trading import (
    DEFAULT_COSTS,
    Level,
    OptionCode,
    make_card,
    option_values,
    simulate_all,
)

P0 = 100.0
ATR = 2.0
Q = (100.0, 100.5, 99.5, 100.0)


def _future(*bars: tuple[float, float, float, float], total: int = 120) -> list[list[float]]:
    rows = [list(b) for b in bars]
    while len(rows) < total:
        rows.append(list(Q))
    return rows


def _entries(n_per_label: int, labels: list[str]) -> list[PoolEntry]:
    entries = []
    for label in labels:
        for i in range(n_per_label):
            entries.append(
                PoolEntry(
                    snapshot_id=f"{label}-{i}",
                    ticker="AAA",
                    t0=date(2020, 1, 1),
                    label=label,
                )
            )
    return entries


def test_draw_strata() -> None:
    labels = ["K10", "K30", "K120", "W10", "W30", "W120"]
    entries = _entries(10, labels)
    rng = random.Random(7)
    counts: dict[str, int] = {}
    seen: dict[str, int] = {}
    for _ in range(600):
        picked = draw_snapshot(entries, seen, rng)
        assert picked is not None
        seen[picked.snapshot_id] = seen.get(picked.snapshot_id, 0) + 1
        counts[picked.label] = counts.get(picked.label, 0) + 1
    for label in labels:
        assert 60 <= counts[label] <= 140


def test_draw_least_played() -> None:
    entries = _entries(1, ["K10"]) * 1
    entries = [
        PoolEntry(snapshot_id=f"s{i}", ticker="AAA", t0=date(2020, 1, 1), label="K10")
        for i in range(5)
    ]
    play_counts = {e.snapshot_id: 1 for e in entries}
    play_counts["s2"] = 0
    rng = random.Random(1)
    picked = draw_snapshot(entries, play_counts, rng)
    assert picked is not None
    assert picked.snapshot_id == "s2"


def test_draw_exhausted_pool_repeats() -> None:
    entries = [
        PoolEntry(snapshot_id=f"s{i}", ticker="AAA", t0=date(2020, 1, 1), label="K10")
        for i in range(60)
    ]
    rng = random.Random(3)
    seen: dict[str, int] = {}
    for _ in range(60):
        picked = draw_snapshot(entries, seen, rng)
        assert picked is not None
        seen[picked.snapshot_id] = seen.get(picked.snapshot_id, 0) + 1
    assert all(v == 1 for v in seen.values())

    picked_61 = draw_snapshot(entries, seen, rng)
    assert picked_61 is not None
    assert seen[picked_61.snapshot_id] == 1


def test_draw_all_excluded_returns_none() -> None:
    entries = _entries(1, ["K10", "W10"])
    exclude = frozenset(e.snapshot_id for e in entries)
    assert draw_snapshot(entries, {}, random.Random(1), exclude=exclude) is None


def test_resolve_matches_trading() -> None:
    user = UserRow(
        id=1,
        name="Test",
        start_capital_cents=1_000_000,
        balance_cents=1_000_000,
        lev_mid=5,
        lev_pro=10,
        interest_tenths=50,
        fee_tenths=20,
    )
    setting = setting_for(user, Level.PROFI)
    snap = SnapshotBars(p0=P0, atr=ATR, future=_future(Q, (99.0, 111.0, 98.0, 100.0)))

    res = resolve(snap, setting, OptionCode.K30)

    balance = Decimal(user.balance_cents) / 100
    card = make_card(30, P0, ATR, balance, setting.leverage, DEFAULT_COSTS)
    results = simulate_all(
        {OptionCode.K30: card, OptionCode.K10: card, OptionCode.K120: card}, snap.future
    )
    values = option_values(results, balance)

    assert res.outcomes[OptionCode.K30].value == pytest.approx(values[OptionCode.K30])
    assert res.outcomes[OptionCode.K30].points >= 0


def test_wait_books_nothing() -> None:
    user = UserRow(1, "Test", 1_000_000, 1_000_000, 5, 10, 50, 20)
    setting = setting_for(user, Level.EINFACH)
    snap = SnapshotBars(p0=P0, atr=ATR, future=_future(Q, (99.0, 111.0, 98.0, 100.0)))

    res = resolve(snap, setting, OptionCode.W30)

    assert res.balance_after == setting.balance
    assert res.pnl == Decimal(0)


def test_k_locked_raises_and_w_uses_start_capital() -> None:
    user = UserRow(1, "Test", 1_000_000, 99_00, 5, 10, 50, 20)
    setting = setting_for(user, Level.EINFACH)
    snap = SnapshotBars(p0=P0, atr=ATR, future=_future(Q, (99.0, 111.0, 98.0, 100.0)))

    with pytest.raises(ValueError, match="gesperrt"):
        resolve(snap, setting, OptionCode.K30)

    res = resolve(snap, setting, OptionCode.W30)
    ref = Decimal(user.start_capital_cents) / 100
    card = make_card(30, P0, ATR, ref, setting.leverage, setting.costs)
    results = simulate_all({OptionCode.K30: card}, snap.future)
    values = option_values(results, ref)
    assert res.outcomes[OptionCode.W30].value == pytest.approx(values[OptionCode.W30])


def test_card_lines_worked_example() -> None:
    user = UserRow(1, "Test", 1_000_000, 1_000_000, 5, 10, 50, 20)
    setting = setting_for(user, Level.PROFI)
    card = make_card(30, P0, ATR, setting.balance, setting.leverage, setting.costs)

    lines = card_lines(card, setting)

    assert lines == [
        "K30 · 30 Tage · Profi",
        "SL -5,00 % → 95,00 · TP +10,00 % → 110,00 · CRV 1 : 2",
        "Einsatz 2.000,00 € (20,00 % von B) · Hebel 10 · Exposure 20.000,00 €",
        "Stückzahl ≈ 200 · Gebühr 40,00 €",
        "Finanzierung (30 Tage) 107,14 € · KO-Abstand -10,00 %",
        "Verlust bei SL 1.040,00 € · Gewinn bei TP 1.960,00 €",
    ]


def test_card_lines_einfach_no_financing() -> None:
    user = UserRow(1, "Test", 1_000_000, 1_000_000, 5, 10, 50, 20)
    setting = setting_for(user, Level.EINFACH)
    card = make_card(30, P0, ATR, setting.balance, setting.leverage, setting.costs)

    lines = card_lines(card, setting)

    assert not any("Finanzierung" in line for line in lines)


def test_wait_lines() -> None:
    assert wait_lines(30) == ["Warten 30 Tage", "Kein Einsatz, keine Kosten"]
