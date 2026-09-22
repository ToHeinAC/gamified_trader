import json
from pathlib import Path

import pandas as pd

from app.pool import build_pool
from app.pool_store import read_meta, read_pool, write_pool
from tests.helpers import random_walk_bars, write_store


def test_round_trip(tmp_path: Path) -> None:
    tickers = ["AAA", "BBB"]
    frames = {t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(tickers)}
    store = write_store(tmp_path / "prices", frames)
    df, report = build_pool(tickers, store.read, 40, seed=1)

    parquet = tmp_path / "snapshots.parquet"
    meta = tmp_path / "snapshots.json"
    write_pool(df, report, parquet, meta)

    round_tripped = read_pool(parquet)
    pd.testing.assert_frame_equal(round_tripped, df)

    meta_back = read_meta(meta)
    assert meta_back == report

    raw = meta.read_text(encoding="utf-8")
    assert list(json.loads(raw).keys()) == sorted(json.loads(raw).keys())
    assert not list(tmp_path.glob("*.tmp"))
