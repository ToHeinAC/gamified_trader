"""Snapshot pool persistence: data/snapshots.parquet and data/snapshots.json."""

import json
import os
from collections.abc import Mapping
from pathlib import Path

import pandas as pd


def write_pool(df: pd.DataFrame, report: Mapping[str, object], parquet: Path, meta: Path) -> None:
    parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp_parquet = parquet.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_parquet, index=False)
    os.replace(tmp_parquet, parquet)

    meta.parent.mkdir(parents=True, exist_ok=True)
    tmp_meta = meta.with_suffix(".json.tmp")
    tmp_meta.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp_meta, meta)


def read_pool(parquet: Path) -> pd.DataFrame:
    return pd.read_parquet(parquet)


def read_meta(meta: Path) -> dict[str, object]:
    return json.loads(meta.read_text(encoding="utf-8"))
