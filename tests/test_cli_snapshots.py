from pathlib import Path

import pytest

from app import cli
from tests.helpers import random_walk_bars, write_store


def test_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    frames = {t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(tickers)}
    write_store(tmp_path / "prices", frames)

    code = cli.main(["snapshots", "build", "--n", "60", "--seed", "1"])

    assert code == 0
    assert (tmp_path / "snapshots.parquet").exists()
    assert (tmp_path / "snapshots.json").exists()
    out = capsys.readouterr().out
    assert "60" in out


def test_build_insufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    tickers = ["AAA", "BBB"]
    frames = {t: random_walk_bars(1600, seed=i, start_price=50.0) for i, t in enumerate(tickers)}
    write_store(tmp_path / "prices", frames)

    code = cli.main(["snapshots", "build", "--n", "100000", "--seed", "1"])

    assert code == 1
    assert "benötigt" in capsys.readouterr().out


def test_build_no_price_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))

    code = cli.main(["snapshots", "build"])

    assert code == 1
    assert "gt data download" in capsys.readouterr().out
