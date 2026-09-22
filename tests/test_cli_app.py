from pathlib import Path

import pytest
from nicegui import ui

from app import cli


def test_port_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path / "existing-storage"))
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(ui, "run", lambda *_a, **kw: calls.append(kw))

    code = cli.main(["app"])

    assert code == 0
    assert calls[0]["port"] == 8537
    assert calls[0]["reload"] is False
    assert calls[0]["show"] is False
    assert (tmp_path / "nicegui").exists()


def test_port_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GT_PORT", "8600")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(ui, "run", lambda *_a, **kw: calls.append(kw))

    cli.main(["app"])

    assert calls[0]["port"] == 8600
