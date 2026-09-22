from pathlib import Path

from app.config import load_config


def test_defaults() -> None:
    cfg = load_config({})
    assert cfg.data_dir == Path("data")
    assert cfg.yahoo_pause_s == 2.0
    assert cfg.prices_dir == Path("data") / "prices"


def test_env_override() -> None:
    cfg = load_config({"GT_DATA_DIR": "/tmp/gt-data", "GT_YAHOO_PAUSE_S": "0.5"})
    assert cfg.data_dir == Path("/tmp/gt-data")
    assert cfg.yahoo_pause_s == 0.5
    assert cfg.prices_dir == Path("/tmp/gt-data") / "prices"
