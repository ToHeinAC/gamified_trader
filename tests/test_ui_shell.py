import re
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from nicegui import app as nicegui_app
from nicegui import ui
from nicegui.testing import User, user_simulation

from app.config import load_config
from app.db import Database
from app.theme import DARK, LIGHT
from app.ui.root import root
from tests.helpers import random_walk_bars, write_store


def _create_user(tmp_path: Path, name: str = "Anna") -> None:
    db = Database(load_config({"GT_DATA_DIR": str(tmp_path)}).db_path)
    db.init()
    db.create_user(name, 10_000, "2026-09-22T10:00:00+00:00")


@pytest.fixture
async def gt_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[User]:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    async with user_simulation(root=root) as user:
        user.javascript_rules[re.compile(".*prefers-color-scheme.*")] = lambda _m: False
        yield user


async def test_no_user_shows_hint(gt_user: User) -> None:
    await gt_user.open("/")
    await gt_user.should_see("Noch kein Nutzer angelegt.")


async def test_page_loads_with_a_chart(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    write_store(
        tmp_path / "prices",
        {"AAA": random_walk_bars(400, 0), "BBB": random_walk_bars(400, 1)},
    )
    await gt_user.open("/")
    plots = list(gt_user.find(ui.plotly).elements)
    assert len(plots) == 1
    assert "SMA200" in str(plots[0].props["options"])


async def test_no_data_shows_hint(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    await gt_user.open("/")
    await gt_user.should_see("gt data download")


async def test_system_dark_is_resolved(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(400, 0)})
    gt_user.javascript_rules[re.compile(".*prefers-color-scheme.*")] = lambda _m: True
    await gt_user.open("/")

    async def _dark_stored() -> bool:
        return nicegui_app.storage.general.get("dark_mode") is True

    await _eventually(_dark_stored)
    plots = list(gt_user.find(ui.plotly).elements)
    assert DARK.surface in str(plots[0].props["options"])


async def test_toggle_theme(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(400, 0)})
    gt_user.javascript_rules[re.compile(".*prefers-color-scheme.*")] = lambda _m: True
    await gt_user.open("/")

    async def _dark_stored() -> bool:
        return nicegui_app.storage.general.get("dark_mode") is True

    await _eventually(_dark_stored)
    gt_user.find("Hell/Dunkel").click()

    async def _light_stored() -> bool:
        return nicegui_app.storage.general.get("dark_mode") is False

    await _eventually(_light_stored)
    plots = list(gt_user.find(ui.plotly).elements)
    assert LIGHT.surface in str(plots[0].props["options"])


async def test_stored_choice_wins_over_system(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(400, 0)})
    nicegui_app.storage.general["dark_mode"] = False
    gt_user.javascript_rules[re.compile(".*prefers-color-scheme.*")] = lambda _m: True
    await gt_user.open("/")
    assert nicegui_app.storage.general.get("dark_mode") is False


async def test_shutdown_button(
    gt_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_user(tmp_path)
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(400, 0)})
    shutdown = MagicMock()
    monkeypatch.setattr(nicegui_app, "shutdown", shutdown)
    await gt_user.open("/")
    gt_user.find("App beenden").click()
    shutdown.assert_called_once()


async def test_preset_button(gt_user: User, tmp_path: Path) -> None:
    _create_user(tmp_path)
    write_store(tmp_path / "prices", {"AAA": random_walk_bars(400, 0)})
    await gt_user.open("/")
    gt_user.find("3M").click()

    async def _range_set() -> bool:
        plots = list(gt_user.find(ui.plotly).elements)
        options = plots[0].props["options"]
        return list(options["layout"]["xaxis"]["range"]) == [-62.5, 0.5]

    await _eventually(_range_set)


async def _eventually(check, timeout: float = 1.0) -> None:
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while not await check():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)
