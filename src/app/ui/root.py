"""App shell: header, theme resolution, routing. Shared by `ui.run` and tests."""

from typing import cast

from nicegui import app as nicegui_app
from nicegui import ui

from app.config import Config
from app.theme import page_css
from app.ui.play import play_page

DETECT_DARK_JS = "window.matchMedia('(prefers-color-scheme: dark)').matches"


def root() -> None:
    ui.add_css(page_css())
    dark = ui.dark_mode(None).bind_value(nicegui_app.storage.general, "dark_mode")
    ui.timer(0, lambda: _resolve_system_theme(dark), once=True)
    _header(dark)
    ui.sub_pages({"/": lambda: play_page(dark)})


async def _resolve_system_theme(dark: ui.dark_mode) -> None:
    if dark.value is None:
        dark.set_value(cast(bool, await ui.run_javascript(DETECT_DARK_JS)))


def _header(dark: ui.dark_mode) -> None:
    with ui.header().classes("gt-header"):
        ui.label("Gamified Trader")
        ui.link("Spielen", "/")
        ui.space()
        ui.button("Hell/Dunkel", on_click=lambda: dark.set_value(not bool(dark.value)))
        ui.button("App beenden", on_click=lambda: nicegui_app.shutdown())


def run_app(cfg: Config) -> None:
    # NiceGUI 3.17.1 types `root` as a bare `Callable`, which strict mode reports as Unknown;
    # this is a gap in nicegui's own stub, not in our code (verified in isolation).
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        root, port=cfg.port, title="Gamified Trader", reload=False, show=False
    )
