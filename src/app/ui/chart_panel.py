"""Plotly panel with optional preset buttons, reused by decision and resolution views."""

from collections.abc import Callable

import pandas as pd
from nicegui import ui

from app.chart import PRESETS, START_PRESET, Figure, apply_preset
from app.theme import Theme, theme_for
from app.ui.context import PageContext


def chart_panel(
    ctx: PageContext,
    window: pd.DataFrame,
    make_figure: Callable[[Theme], Figure],
    presets: bool = True,
) -> ui.plotly:
    """`make_figure` builds the figure for a theme (the caller's closure may add a preview).
    With `presets`, preset buttons re-apply `apply_preset` on top of a freshly built figure."""
    state = {"preset": START_PRESET}

    def _figure() -> Figure:
        fig = make_figure(theme_for(ctx.dark.value is True))
        if presets:
            apply_preset(fig, window, state["preset"])
        return fig

    with ui.card().classes("gt-card"):
        if presets:
            with ui.row():
                for name in PRESETS:
                    ui.button(name, on_click=lambda _e, n=name: _select_preset(n))
        plot = ui.plotly(_figure()).classes("w-full h-[420px] lg:h-[720px]")

    # ui.plotly.update_figure's signature references plotly's unstubbed Figure type, which
    # nicegui itself doesn't re-stub; same NiceGUI/plotly stub gap as ui/root.py's ui.run.
    def _select_preset(name: str) -> None:
        state["preset"] = name
        plot.update_figure(_figure())  # pyright: ignore[reportUnknownMemberType]

    def _on_dark_change() -> None:
        if plot.is_deleted:
            return
        plot.update_figure(_figure())  # pyright: ignore[reportUnknownMemberType]

    ctx.dark.on_value_change(_on_dark_change)
    return plot
