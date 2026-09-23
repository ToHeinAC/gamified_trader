"""Round-trip tests for app.model_store."""

from pathlib import Path

import pandas as pd

from app import model_store


class _DummyModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _DummyModel) and other.value == self.value


def test_features_round_trip(tmp_path: Path) -> None:
    df = pd.DataFrame({"snapshot_id": ["a", "b"], "ret_5": [0.1, None]})
    path = tmp_path / "features.parquet"
    model_store.write_features(df, path)
    loaded = model_store.read_features(path)
    assert loaded["snapshot_id"].tolist() == ["a", "b"]
    assert set(tmp_path.iterdir()) == {path}


def test_model_and_meta_round_trip(tmp_path: Path) -> None:
    models = {(1, 10, 0.25): _DummyModel(1.0), (5, 30, 0.5): _DummyModel(2.0)}
    metadata = {"seed": 42, "levels": [1, 5, 10]}
    model_path = tmp_path / "models" / "model.joblib"
    meta_path = tmp_path / "models" / "model.json"

    model_store.write_model(models, metadata, model_path, meta_path)

    loaded_models = model_store.read_model(model_path)
    assert loaded_models == models
    loaded_meta = model_store.read_meta(meta_path)
    assert loaded_meta == metadata
    assert set((tmp_path / "models").iterdir()) == {model_path, meta_path}


def test_market_round_trip(tmp_path: Path) -> None:
    market = pd.DataFrame(
        {"mkt_ret_20": [0.01, None], "mkt_breadth200": [0.5, 0.6]},
        index=pd.DatetimeIndex(pd.to_datetime(["2020-01-02", "2020-01-03"]), name="date"),
    )
    path = tmp_path / "market.parquet"
    model_store.write_market(market, path)
    loaded = model_store.read_market(path)
    assert loaded.index.name == "date"
    pd.testing.assert_frame_equal(loaded, market, check_freq=False)
    assert set(tmp_path.iterdir()) == {path}
