import json
import re
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.chart import (
    MAX_WINDOW,
    PRESETS,
    START_PRESET,
    TRACE_NAMES,
    add_preview,
    apply_preset,
    build_discover_figure,
    build_figure,
    build_resolution_figure,
    decision_window,
    discover_window,
    resolution_window,
)
from app.game import SnapshotBars, resolve, setting_for
from app.indicators import with_indicators
from app.theme import DARK, LIGHT
from app.trading import DEFAULT_COSTS, Level, OptionCode, make_card
from tests.helpers import make_bars, random_walk_bars


def _window(n: int, t0_idx: int | None = None, seed: int = 0):
    bars = random_walk_bars(n, seed)
    indexed = with_indicators(bars)
    return decision_window(indexed, n - 1 if t0_idx is None else t0_idx)


def _trace(fig, name: str) -> dict:
    return next(t for t in fig.to_dict()["data"] if t["name"] == name)


def test_structure() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    d = fig.to_dict()
    names = [t["name"] for t in d["data"]]
    assert names == list(TRACE_NAMES)
    assert "yaxis3" in d["layout"]
    assert "yaxis4" not in d["layout"]
    assert d["layout"]["yaxis"]["side"] == "right"
    assert tuple(d["layout"]["yaxis3"]["range"]) == (0, 100)
    kurs = _trace(fig, "Kurs")
    assert list(kurs["x"])[-1] == 0


def test_window_length() -> None:
    window_long = _window(1500)
    assert len(window_long) == 1260

    window_short = _window(300)
    assert len(window_short) == 300


def test_sma200_from_first_visible() -> None:
    window = _window(1500)
    assert window["sma200"].notna().all()


def test_short_history() -> None:
    window = _window(300)
    assert window["sma200"].iloc[:199].isna().all()
    fig = build_figure(window, LIGHT)
    sma200 = _trace(fig, "SMA200")
    assert np.isnan(np.asarray(sma200["y"], dtype=float)).any()


def test_no_leak() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    fig_json = fig.to_json(engine="json")
    assert fig_json is not None
    assert not re.search(r"\d{4}-\d{2}-\d{2}", fig_json)
    assert "date" not in window.columns


def test_presets() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    for preset, n_preset in PRESETS.items():
        apply_preset(fig, window, preset)
        n = min(n_preset, len(window))
        layout = fig.to_dict()["layout"]
        assert tuple(layout["xaxis"]["range"]) == pytest.approx((-n + 0.5, 0.5))
        vis = window.tail(n)
        lo = np.nanmin(np.minimum(vis["low"], vis["bb_lower"]))
        hi = np.nanmax(np.maximum(vis["high"], vis["bb_upper"]))
        assert tuple(layout["yaxis"]["range"]) == pytest.approx((lo * 0.97, hi * 1.03))

    fig2 = build_figure(window, LIGHT)
    n = min(PRESETS[START_PRESET], len(window))
    assert tuple(fig2.to_dict()["layout"]["xaxis"]["range"]) == pytest.approx((-n + 0.5, 0.5))


def test_theme_colours() -> None:
    window = _window(400)
    fig_light = build_figure(window, LIGHT)
    assert fig_light.to_dict()["layout"]["paper_bgcolor"] == LIGHT.surface
    kurs_light = _trace(fig_light, "Kurs")
    assert kurs_light["increasing"]["line"]["color"] == "#22B35E"

    fig_dark = build_figure(window, DARK)
    assert fig_dark.to_dict()["layout"]["paper_bgcolor"] == DARK.surface


def test_volume_colours() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    volume = _trace(fig, "Volumen")
    falling_idx = next(
        i for i in range(len(window)) if window["close"].iloc[i] < window["open"].iloc[i]
    )
    assert list(volume["marker"]["color"])[falling_idx] == LIGHT.down


def test_constant_prices_and_zero_volume_builds() -> None:
    bars = make_bars([10.0] * 300, volume=0)
    indexed = with_indicators(bars)
    window = decision_window(indexed, 299)
    build_figure(window, LIGHT)


def test_window_json_serializable() -> None:
    window = _window(300)
    fig = build_figure(window, LIGHT)
    fig_json = fig.to_json()
    assert fig_json is not None
    json.loads(fig_json)


def test_preview_k_profi() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    card = make_card(30, 100.0, 2.0, Decimal("10000.00"), 10, DEFAULT_COSTS)

    add_preview(fig, OptionCode.K30, card, LIGHT)

    d = fig.to_dict()
    names = {t["name"] for t in d["data"]}
    for name, price in (
        ("Vorschau SL", card.sl_price),
        ("Vorschau TP", card.tp_price),
        ("Vorschau KO", card.ko_price),
    ):
        assert price is not None
        assert name in names
        trace = next(t for t in d["data"] if t["name"] == name)
        assert list(trace["x"]) == [0, 30]
        assert all(y == pytest.approx(float(price)) for y in trace["y"])
    assert d["layout"]["xaxis"]["range"][1] == pytest.approx(30.5)


def test_preview_k_einfach_no_ko() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    card = make_card(30, 100.0, 2.0, Decimal("10000.00"), 1, DEFAULT_COSTS)

    add_preview(fig, OptionCode.K30, card, LIGHT)

    names = {t["name"] for t in fig.to_dict()["data"]}
    assert "Vorschau KO" not in names


def test_preview_w() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)

    add_preview(fig, OptionCode.W30, None, LIGHT)

    shapes = fig.to_dict()["layout"]["shapes"]
    assert any(s["x0"] == s["x1"] == 30 for s in shapes)


def test_resolution_figure() -> None:
    from app.db import UserRow

    bars = random_walk_bars(500, seed=0)
    ind = with_indicators(bars)
    t0_idx = 300
    window = resolution_window(ind, t0_idx)

    user = UserRow(1, "Test", 1_000_000, 1_000_000, 5, 10, 50, 20)
    setting = setting_for(user, Level.EINFACH)
    snap = SnapshotBars(
        p0=float(ind["close"].iloc[t0_idx]),
        atr=float(ind["atr14"].iloc[t0_idx]),
        future=ind[["open", "high", "low", "close"]]
        .iloc[t0_idx + 1 : t0_idx + 121]
        .to_numpy()
        .tolist(),
    )
    res = resolve(snap, setting, OptionCode.K30)

    fig = build_resolution_figure(window, LIGHT, res)
    d = fig.to_dict()
    assert list(d["data"][0]["x"])[-1] == 120
    shapes = d["layout"]["shapes"]
    assert any(s.get("x0") == 0.5 for s in shapes)
    einstieg = next(t for t in d["data"] if t["name"] == "Einstieg")
    assert list(einstieg["x"]) == [1]


def test_discover_window_keeps_dates_and_length() -> None:
    ind = with_indicators(random_walk_bars(300, seed=1))
    window = discover_window(ind)
    assert "date" in window.columns
    assert window["x"].dtype.kind == "M"
    assert len(window) == min(MAX_WINDOW, len(ind))
    assert (window["x"] == window["date"]).all()


def test_discover_figure_title_and_dates() -> None:
    bars = random_walk_bars(300, seed=5)
    window = discover_window(with_indicators(bars))
    fig = build_discover_figure(window, LIGHT, "AAPL", "Apple Inc.")
    assert fig.layout.title.text == "AAPL · Apple Inc."
    candle = _trace(fig, "Kurs")
    assert pd.Timestamp(candle["x"][0]) == window["x"].iloc[0]


def test_discover_figure_rangebreaks_hide_missing_days() -> None:
    raw = random_walk_bars(60, seed=2, start="2024-01-02")
    holiday = raw["date"].iloc[10]
    bars = raw.drop(index=10).reset_index(drop=True)
    window = discover_window(with_indicators(bars))

    fig = build_discover_figure(window, LIGHT, "AAA", "AAA Inc.")

    values = set(fig.layout.xaxis.rangebreaks[0].values)
    assert holiday.strftime("%Y-%m-%d") in values
    some_saturday = (window["x"].iloc[0] + pd.offsets.Week(weekday=5)).normalize()
    assert some_saturday.strftime("%Y-%m-%d") in values
    bar_days = set(window["x"].dt.strftime("%Y-%m-%d"))
    assert not (values & bar_days)


def test_discover_figure_seven_day_week_has_no_rangebreaks() -> None:
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    bars = make_bars([100.0 + i * 0.1 for i in range(40)]).assign(
        date=pd.DatetimeIndex(dates).astype("datetime64[ns]")
    )
    window = discover_window(with_indicators(bars))
    fig = build_discover_figure(window, LIGHT, "BTC-USD", "Bitcoin")
    assert not fig.layout.xaxis.rangebreaks


def test_discover_preset_sets_date_range() -> None:
    bars = random_walk_bars(300, seed=3)
    window = discover_window(with_indicators(bars))
    fig = build_discover_figure(window, LIGHT, "AAA", "AAA Inc.")

    apply_preset(fig, window, "3M")

    n = min(PRESETS["3M"], len(window))
    vis = window.tail(n)
    expected_start = vis["x"].iloc[0] - pd.Timedelta(hours=12)
    expected_end = vis["x"].iloc[-1] + pd.Timedelta(hours=12)
    x_range = fig.layout.xaxis.range
    assert pd.Timestamp(x_range[0]) == expected_start
    assert pd.Timestamp(x_range[1]) == expected_end


def test_game_figures_unaffected_by_date_aware_presets() -> None:
    window = _window(400)
    fig = build_figure(window, LIGHT)
    fig_json = fig.to_json(engine="json")
    assert fig_json is not None
    assert not re.search(r"\d{4}-\d{2}-\d{2}", fig_json)


def test_discover_figure_is_orjson_serializable() -> None:
    """Regression: NiceGUI's ui.plotly sends fig.to_plotly_json() through orjson (verified against
    the real dependency), which accepts datetime.datetime but rejects pandas.Timestamp. Plotly's
    own to_json()/to_dict() can't catch this: it stringifies dates itself."""
    import orjson

    bars = random_walk_bars(300, seed=6)
    window = discover_window(with_indicators(bars))
    fig = build_discover_figure(window, LIGHT, "AAA", "AAA Inc.")
    apply_preset(fig, window, "3M")

    orjson.dumps(fig.to_plotly_json())  # raises TypeError if a pandas.Timestamp leaked in


def test_game_figure_is_orjson_serializable() -> None:
    import orjson

    window = _window(400)
    fig = build_figure(window, LIGHT)
    orjson.dumps(fig.to_plotly_json())
