from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import cli, model_store, yahoo
from app.config import load_config
from tests.helpers import make_bars, random_walk_bars, write_store


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


def test_download_writes_market_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GT_YAHOO_PAUSE_S", "0")
    tickers = ["AAA", "BBB"]
    frames = {t: random_walk_bars(60, seed=i) for i, t in enumerate(tickers)}

    def fake_fetch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
        return {t: frames[t] for t in tickers}

    monkeypatch.setattr(yahoo, "fetch_batch", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda s: None)

    code = cli.main(["data", "download", "--tickers", *tickers])

    assert code == 0
    cfg = load_config()
    assert cfg.market_parquet.exists()
    market = model_store.read_market(cfg.market_parquet)
    last_store_date = max(df["date"].iloc[-1] for df in frames.values())
    assert market.index.max() == last_store_date
    assert "Markttabelle bis" in capsys.readouterr().out


def test_update_refreshes_market_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(60, seed=1)})

    monkeypatch.setattr(yahoo, "fetch_batch", lambda tickers, start: {})
    monkeypatch.setattr("time.sleep", lambda s: None)

    code = cli.main(["data", "update"])

    assert code == 0
    cfg = load_config()
    assert cfg.market_parquet.exists()
    assert "Markttabelle bis" in capsys.readouterr().out


def test_download_no_tickers_skips_market_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(yahoo, "fetch_batch", lambda tickers, start: {})
    monkeypatch.setattr("time.sleep", lambda s: None)

    cli.main(["data", "download", "--tickers", "AAA"])

    cfg = load_config()
    assert not cfg.market_parquet.exists()
