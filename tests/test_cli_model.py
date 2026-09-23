from pathlib import Path

import pytest

from app import cli
from tests.helpers import random_walk_bars, write_store


def test_train(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    frames = {t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(tickers)}
    write_store(tmp_path / "prices", frames)
    assert cli.main(["snapshots", "build", "--n", "60", "--seed", "1"]) == 0

    code = cli.main(["model", "train", "--seed", "1"])

    assert code == 0
    assert (tmp_path / "features.parquet").exists()
    assert (tmp_path / "models" / "model.joblib").exists()
    assert (tmp_path / "models" / "model.json").exists()
    out = capsys.readouterr().out
    assert "Ø V Modell" in out


def test_train_no_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))

    code = cli.main(["model", "train"])

    assert code == 1
    assert "gt snapshots build" in capsys.readouterr().out
