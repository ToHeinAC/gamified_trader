"""Shared test factories for synthetic price frames."""

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import Config
from app.price_store import PriceStore


def make_bars(
    closes: Sequence[float],
    *,
    start: str = "2001-01-02",
    spread: float = 0.01,
    volume: int = 1_000_000,
) -> pd.DataFrame:
    """Valid OHLCV frame on business days.

    open = previous close (first row: close), high = max(open, close) * (1 + spread),
    low = min(open, close) * (1 - spread).
    """
    dates = pd.bdate_range(start=start, periods=len(closes))
    opens = [closes[0], *closes[:-1]]
    highs = [max(o, c) * (1 + spread) for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) * (1 - spread) for o, c in zip(opens, closes, strict=True)]
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
            "open": pd.Series(opens, dtype="float64"),
            "high": pd.Series(highs, dtype="float64"),
            "low": pd.Series(lows, dtype="float64"),
            "close": pd.Series(closes, dtype="float64"),
            "volume": pd.Series([volume] * len(closes), dtype="int64"),
        }
    )


def random_walk_bars(
    n: int,
    seed: int,
    *,
    start_price: float = 50.0,
    sigma: float = 0.02,
    start: str = "2001-01-02",
) -> pd.DataFrame:
    """closes = start_price * exp(cumsum(normal(0, sigma))) with default_rng(seed)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma, size=n)
    closes = start_price * np.exp(np.cumsum(steps))
    return make_bars(closes.tolist(), start=start)


def bars_with_gap(
    n: int, seed: int, gap_at: int, gap_days: int, *, start_price: float = 50.0, sigma: float = 0.02
) -> pd.DataFrame:
    """`random_walk_bars` with every date from `gap_at` on shifted by `gap_days`."""
    bars = random_walk_bars(n, seed, start_price=start_price, sigma=sigma)
    dates = list(bars["date"])
    offset = pd.Timedelta(days=gap_days)
    shifted = [d + offset if i >= gap_at else d for i, d in enumerate(dates)]
    return bars.assign(date=pd.Series(shifted).astype("datetime64[ns]"))


def write_store(root: Path, frames: Mapping[str, pd.DataFrame]) -> PriceStore:
    store = PriceStore(root)
    for ticker, df in frames.items():
        store.write(ticker, df)
    return store


def make_game_env(
    root: Path,
    tickers: Sequence[str] = ("ZZA", "ZZB", "ZZLEAK"),
    n: int = 30,
    seed: int = 1,
) -> tuple[Config, PriceStore, int]:
    """`write_store` with random-walk tickers of 1,600 bars -> `build_pool` -> `write_pool`
    to the config paths -> create the user "Test" (defaults). Returns (cfg, store, user_id)."""
    from app.config import load_config
    from app.db import Database
    from app.pool import build_pool
    from app.pool_store import write_pool

    frames = {t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(tickers)}
    cfg = load_config({"GT_DATA_DIR": str(root)})
    store = write_store(cfg.prices_dir, frames)
    df, report = build_pool(list(tickers), store.read, n, seed)
    write_pool(df, report, cfg.snapshots_parquet, cfg.snapshots_json)

    db = Database(cfg.db_path)
    db.init()
    user_id = db.create_user("Test", 10_000, "2026-09-22T10:00:00+00:00")
    return cfg, store, user_id
