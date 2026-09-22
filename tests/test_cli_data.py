from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import cli, yahoo
from tests.helpers import make_bars, write_store


def test_download_with_tickers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GT_YAHOO_PAUSE_S", "0")
    df = make_bars([10.0, 11.0])

    def fake_fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {t: df for t in tickers}

    monkeypatch.setattr(yahoo, "fetch_batch", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda s: None)

    code = cli.main(["data", "download", "--tickers", "AAA"])

    assert code == 0
    assert (tmp_path / "prices" / "AAA.parquet").exists()
    assert "erfolgreich" in capsys.readouterr().out


def test_download_all_fail_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))

    def fake_fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {}

    monkeypatch.setattr(yahoo, "fetch_batch", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda s: None)

    code = cli.main(["data", "download", "--tickers", "AAA"])
    assert code == 1


def test_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    write_store(tmp_path / "prices", {"AAA": make_bars([10.0, 11.0])})

    def fake_fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {}

    monkeypatch.setattr(yahoo, "fetch_batch", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda s: None)

    code = cli.main(["data", "update"])
    assert code == 0
