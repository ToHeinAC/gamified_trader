# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# Reason: joblib ships no type stubs; untyped calls stay inside this module (D14).
"""Model artifacts: data/features.parquet, data/market.parquet, data/models/model.joblib + .json.

`read_model` only ever loads our own artifact under `GT_DATA_DIR`, never a user-supplied file
(PRD §5 risk: joblib/pickle can execute code on load).
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import joblib
import pandas as pd


def write_features(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def read_features(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write_market(df: pd.DataFrame, path: Path) -> None:
    """Market table (index `date`) as parquet with a `date` column, written atomically."""
    write_features(df.reset_index(), path)


def read_market(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path).set_index("date")


def write_model(
    models: Mapping[tuple[int, int, float], object],
    metadata: Mapping[str, object],
    model_path: Path,
    meta_path: Path,
) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_model = model_path.with_suffix(".joblib.tmp")
    joblib.dump(dict(models), tmp_model)
    os.replace(tmp_model, model_path)

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp_meta, meta_path)


def read_model(model_path: Path) -> dict[tuple[int, int, float], Any]:
    return joblib.load(model_path)


def read_meta(meta_path: Path) -> dict[str, object]:
    return json.loads(meta_path.read_text(encoding="utf-8"))
