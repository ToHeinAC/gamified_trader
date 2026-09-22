# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: plotly/yfinance ship no type stubs; untyped calls stay inside this module (PRD §5 risks).
"""Plotly chart: candles, indicators and preset ranges (PRD R2). Leak-proof: no dates in output."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.theme import Theme

MAX_WINDOW = 1260
PRESETS: dict[str, int] = {"3M": 63, "6M": 126, "1J": 252, "5J": 1260}
START_PRESET = "1J"
Y_PAD = 0.03
TRACE_NAMES = (
    "Kurs",
    "SMA50",
    "SMA200",
    "BB oben",
    "BB Mitte",
    "BB unten",
    "Volumen",
    "RSI14",
    "RSI 30",
    "RSI 70",
)


def decision_window(bars: pd.DataFrame, t0_idx: int) -> pd.DataFrame:
    """Rows max(0, t0_idx - 1259) .. t0_idx of a frame that already has indicators.
    Adds int column x = row - t0_idx (…, -1, 0) and DROPS the date column (leak-proof)."""
    start = max(0, t0_idx - (MAX_WINDOW - 1))
    window = bars.iloc[start : t0_idx + 1].copy()
    window["x"] = np.arange(start, t0_idx + 1) - t0_idx
    return window.drop(columns=["date"]).reset_index(drop=True)


def _col(window: pd.DataFrame, name: str) -> list[float]:
    """Plain Python list: keeps plotly's JSON output free of binary-encoded arrays."""
    return window[name].tolist()


def _add_candlestick(fig: go.Figure, window: pd.DataFrame, x: list[float], theme: Theme) -> None:
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=_col(window, "open"),
            high=_col(window, "high"),
            low=_col(window, "low"),
            close=_col(window, "close"),
            name="Kurs",
            increasing_line_color=theme.up,
            increasing_fillcolor=theme.up,
            decreasing_line_color=theme.down,
            decreasing_fillcolor=theme.down,
        ),
        row=1,
        col=1,
    )


def _add_overlay_lines(fig: go.Figure, window: pd.DataFrame, x: list[float], theme: Theme) -> None:
    fig.add_trace(
        go.Scatter(x=x, y=_col(window, "sma50"), name="SMA50", line_color=theme.accent),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=x, y=_col(window, "sma200"), name="SMA200", line_color=theme.primary),
        row=1,
        col=1,
    )
    for name, column, dash in (
        ("BB oben", "bb_upper", "dash"),
        ("BB Mitte", "bb_mid", "dot"),
        ("BB unten", "bb_lower", "dash"),
    ):
        fig.add_trace(
            go.Scatter(
                x=x, y=_col(window, column), name=name, line={"color": theme.muted, "dash": dash}
            ),
            row=1,
            col=1,
        )


def _add_price_traces(fig: go.Figure, window: pd.DataFrame, theme: Theme) -> None:
    x = _col(window, "x")
    _add_candlestick(fig, window, x, theme)
    _add_overlay_lines(fig, window, x, theme)


def _add_volume_trace(fig: go.Figure, window: pd.DataFrame, theme: Theme) -> None:
    colors = [
        theme.up if c >= o else theme.down
        for c, o in zip(window["close"], window["open"], strict=True)
    ]
    fig.add_trace(
        go.Bar(x=_col(window, "x"), y=_col(window, "volume"), name="Volumen", marker_color=colors),
        row=2,
        col=1,
    )


def _add_rsi_traces(fig: go.Figure, window: pd.DataFrame, theme: Theme) -> None:
    x = _col(window, "x")
    x_ends = [x[0], x[-1]]
    fig.add_trace(
        go.Scatter(x=x, y=_col(window, "rsi14"), name="RSI14", line_color=theme.primary),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x_ends, y=[30, 30], name="RSI 30", line={"color": theme.muted, "dash": "dash"}
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x_ends, y=[70, 70], name="RSI 70", line={"color": theme.muted, "dash": "dash"}
        ),
        row=3,
        col=1,
    )


def build_figure(window: pd.DataFrame, theme: Theme) -> go.Figure:
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.15, 0.25],
    )
    _add_price_traces(fig, window, theme)
    _add_volume_trace(fig, window, theme)
    _add_rsi_traces(fig, window, theme)

    fig.update_yaxes(side="right", gridcolor=theme.grid)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_xaxes(rangeslider_visible=False, gridcolor=theme.grid)
    fig.update_layout(
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font_color=theme.text,
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
    )
    apply_preset(fig, window, START_PRESET)
    return fig


def preset_ranges(
    window: pd.DataFrame, preset: str
) -> tuple[tuple[float, float], tuple[float, float]]:
    n = min(PRESETS[preset], len(window))
    vis = window.tail(n)
    x_last = float(vis["x"].iloc[-1])
    lo = float(np.nanmin(np.minimum(vis["low"], vis["bb_lower"])))
    hi = float(np.nanmax(np.maximum(vis["high"], vis["bb_upper"])))
    return (x_last - n + 0.5, x_last + 0.5), (lo * (1 - Y_PAD), hi * (1 + Y_PAD))


def apply_preset(fig: go.Figure, window: pd.DataFrame, preset: str) -> None:
    x_range, y_range = preset_ranges(window, preset)
    fig.update_xaxes(range=list(x_range))
    fig.update_yaxes(range=list(y_range), row=1, col=1)
