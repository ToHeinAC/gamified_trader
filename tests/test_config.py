from pathlib import Path

from app.config import load_config


def test_defaults() -> None:
    cfg = load_config({})
    assert cfg.data_dir == Path("data")
    assert cfg.yahoo_pause_s == 2.0
    assert cfg.port == 8537
    assert cfg.prices_dir == Path("data") / "prices"
    assert cfg.snapshots_parquet == Path("data") / "snapshots.parquet"
    assert cfg.snapshots_json == Path("data") / "snapshots.json"
    assert cfg.db_path == Path("data") / "app.db"
    assert cfg.discover_dir == Path("data") / "discover"


def test_env_override() -> None:
    cfg = load_config({"GT_DATA_DIR": "/tmp/gt-data", "GT_YAHOO_PAUSE_S": "0.5", "GT_PORT": "9000"})
    assert cfg.data_dir == Path("/tmp/gt-data")
    assert cfg.yahoo_pause_s == 0.5
    assert cfg.port == 9000
    assert cfg.prices_dir == Path("/tmp/gt-data") / "prices"
