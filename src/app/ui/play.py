"""Page "Spielen" (M2 version; M6 replaces the body)."""

import random

import pandas as pd
from nicegui import ui

from app.chart import decision_window
from app.config import load_config
from app.indicators import with_indicators
from app.price_store import PriceStore
from app.ui.chart_panel import chart_panel

MIN_ROWS = 250


def pick_random_chart(store: PriceStore, rng: random.Random) -> tuple[pd.DataFrame, int] | None:
    """Random ticker with >= 250 rows; t0_idx uniform in [249, len - 1]. None if none qualifies."""
    candidates: list[tuple[str, pd.DataFrame]] = []
    for ticker in store.tickers():
        bars = store.read(ticker)
        if len(bars) >= MIN_ROWS:
            candidates.append((ticker, bars))
    if not candidates:
        return None
    _ticker, bars = rng.choice(candidates)
    t0_idx = rng.randint(MIN_ROWS - 1, len(bars) - 1)
    return bars, t0_idx


def play_page(dark: ui.dark_mode) -> None:
    cfg = load_config()
    picked = pick_random_chart(PriceStore(cfg.prices_dir), random.Random())
    if picked is None:
        ui.label("Keine Kursdaten gefunden. Bitte zuerst `gt data download` ausführen.")
        return
    bars, t0_idx = picked
    chart_panel(decision_window(with_indicators(bars), t0_idx), dark)
