"""Preset buttons + plotly panel, reused unchanged in M6."""

import pandas as pd
from nicegui import ui

from app.chart import PRESETS, START_PRESET, apply_preset, build_figure
from app.theme import theme_for
from app.ui.context import PageContext


def chart_panel(window: pd.DataFrame, ctx: PageContext) -> ui.plotly:
    preset = {"current": START_PRESET}

    def _figure():
        fig = build_figure(window, theme_for(ctx.dark.value is True))
        apply_preset(fig, window, preset["current"])
        return fig

    with ui.card().classes("gt-card"):
        with ui.row():
            for name in PRESETS:
                ui.button(name, on_click=lambda _e, n=name: _select_preset(n))
        plot = ui.plotly(_figure()).classes("w-full h-[640px]")

    # ui.plotly.update_figure's signature references plotly's unstubbed Figure type, which
    # nicegui itself doesn't re-stub; same NiceGUI/plotly stub gap as ui/root.py's ui.run.
    def _select_preset(name: str) -> None:
        preset["current"] = name
        plot.update_figure(_figure())  # pyright: ignore[reportUnknownMemberType]

    def _on_dark_change() -> None:
        if plot.is_deleted:
            return
        plot.update_figure(_figure())  # pyright: ignore[reportUnknownMemberType]

    ctx.dark.on_value_change(_on_dark_change)
    return plot
