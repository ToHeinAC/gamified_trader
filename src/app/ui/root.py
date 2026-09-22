"""App shell: header, theme resolution, routing. Shared by `ui.run` and tests."""

from typing import cast

from nicegui import app as nicegui_app
from nicegui import ui

from app.config import Config, load_config
from app.db import Database
from app.theme import page_css
from app.ui.context import PageContext
from app.ui.play import play_page
from app.ui.setup import setup_page

DETECT_DARK_JS = "window.matchMedia('(prefers-color-scheme: dark)').matches"


def root() -> None:
    ui.add_css(page_css())
    cfg = load_config()
    db = Database(cfg.db_path)
    db.init()
    dark = ui.dark_mode(None).bind_value(nicegui_app.storage.general, "dark_mode")
    ui.timer(0, lambda: _resolve_system_theme(dark), once=True)

    ctx = PageContext(cfg=cfg, db=db, dark=dark)
    ctx.refresh_user_name()
    _header(ctx)
    ui.sub_pages({"/": lambda: play_page(ctx), "/setup": lambda: setup_page(ctx)})


async def _resolve_system_theme(dark: ui.dark_mode) -> None:
    if dark.value is None:
        dark.set_value(cast(bool, await ui.run_javascript(DETECT_DARK_JS)))


def _header(ctx: PageContext) -> None:
    with ui.header().classes("gt-header"):
        ui.label("Gamified Trader")
        ui.link("Spielen", "/")
        ui.link("Setup", "/setup")
        ui.label().bind_text_from(ctx, "user_name")
        ui.space()
        ui.button("Hell/Dunkel", on_click=lambda: ctx.dark.set_value(not bool(ctx.dark.value)))
        ui.button("App beenden", on_click=lambda: nicegui_app.shutdown())


def run_app(cfg: Config) -> None:
    # NiceGUI 3.17.1 types `root` as a bare `Callable`, which strict mode reports as Unknown;
    # this is a gap in nicegui's own stub, not in our code (verified in isolation).
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        root, port=cfg.port, title="Gamified Trader", reload=False, show=False
    )
