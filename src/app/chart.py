# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: plotly/yfinance ship no type stubs; untyped calls stay inside this module (PRD §5 risks).
"""Plotly chart: candles, indicators and preset ranges (PRD R2). Leak-proof: no dates in output."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.game import Resolution
from app.theme import Theme
from app.trading import Card, ExitReason, OptionCode, horizon_of, is_buy

Figure = go.Figure
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


XRange = tuple[float, float] | tuple[pd.Timestamp, pd.Timestamp]
_HALF_DAY = pd.Timedelta(hours=12)


def _x_range(vis: pd.DataFrame, n: int) -> XRange:
    if pd.api.types.is_datetime64_any_dtype(vis["x"]):
        return (
            pd.Timestamp(vis["x"].iloc[0]) - _HALF_DAY,
            pd.Timestamp(vis["x"].iloc[-1]) + _HALF_DAY,
        )
    x_last = float(vis["x"].iloc[-1])
    return (x_last - n + 0.5, x_last + 0.5)


def preset_ranges(window: pd.DataFrame, preset: str) -> tuple[XRange, tuple[float, float]]:
    n = min(PRESETS[preset], len(window))
    vis = window.tail(n)
    lo = float(np.nanmin(np.minimum(vis["low"], vis["bb_lower"])))
    hi = float(np.nanmax(np.maximum(vis["high"], vis["bb_upper"])))
    return _x_range(vis, n), (lo * (1 - Y_PAD), hi * (1 + Y_PAD))


def apply_preset(fig: go.Figure, window: pd.DataFrame, preset: str) -> None:
    x_range, y_range = preset_ranges(window, preset)
    fig.update_xaxes(range=list(x_range))
    fig.update_yaxes(range=list(y_range), row=1, col=1)


EXIT_LABELS = {
    ExitReason.TP: "Take-Profit",
    ExitReason.SL: "Stop-Loss",
    ExitReason.KO: "Knock-out",
    ExitReason.TIME: "Zeit",
}


def _preview_k(fig: go.Figure, card: Card, horizon: int, theme: Theme) -> None:
    x = [0, horizon]
    fig.add_trace(
        go.Scatter(x=x, y=[float(card.sl_price)] * 2, name="Vorschau SL", line_color=theme.down)
    )
    fig.add_trace(
        go.Scatter(x=x, y=[float(card.tp_price)] * 2, name="Vorschau TP", line_color=theme.up)
    )
    if card.ko_price is not None:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=[float(card.ko_price)] * 2,
                name="Vorschau KO",
                line={"color": theme.muted, "dash": "dot"},
            )
        )


def add_preview(fig: go.Figure, option: OptionCode, card: Card | None, theme: Theme) -> None:
    """K: horizontal preview lines for SL/TP(/KO) over x in [0, H]. W: a dashed vline at x = H.
    Extends the x range's right edge to H + 0.5 (all prices are already on the P0 basis)."""
    horizon = horizon_of(option)
    if is_buy(option):
        assert card is not None
        _preview_k(fig, card, horizon, theme)
    else:
        fig.add_vline(x=horizon, line_dash="dash", annotation_text=f"Tag {horizon}")

    current_range = fig.to_dict()["layout"].get("xaxis", {}).get("range")
    left = current_range[0] if current_range else None
    fig.update_xaxes(range=[left, horizon + 0.5])


def resolution_window(ind: pd.DataFrame, t0_idx: int) -> pd.DataFrame:
    """Rows max(0, t0_idx - 1259) .. t0_idx + 120, x = row - t0_idx (… 0 … 120), without date."""
    start = max(0, t0_idx - (MAX_WINDOW - 1))
    end = t0_idx + 120
    window = ind.iloc[start : end + 1].copy()
    window["x"] = np.arange(start, end + 1) - t0_idx
    return window.drop(columns=["date"]).reset_index(drop=True)


def _add_resolution_markers(fig: go.Figure, res: Resolution) -> None:
    horizon = horizon_of(res.chosen)
    if not is_buy(res.chosen):
        fig.add_vline(x=horizon, line_dash="dash")
        return
    result = res.results[horizon]
    fig.add_trace(go.Scatter(x=[1], y=[float(result.entry)], mode="markers", name="Einstieg"))
    fig.add_trace(
        go.Scatter(
            x=[result.exit_day],
            y=[float(result.exit_price)],
            mode="markers",
            name="Ausstieg",
            text=[EXIT_LABELS[result.reason]],
        )
    )


def build_resolution_figure(window: pd.DataFrame, theme: Theme, res: Resolution) -> go.Figure:
    fig = build_figure(window, theme)
    fig.add_vrect(x0=0.5, x1=120.5, fillcolor=theme.accent, opacity=0.08, line_width=0)
    fig.add_vline(x=0, line_dash="dot")
    _add_resolution_markers(fig, res)

    n = PRESETS["1J"]
    fig.update_xaxes(range=[-(n - 0.5), 120.5])
    return fig


def discover_window(ind: pd.DataFrame) -> pd.DataFrame:
    """Last min(1260, len) rows; KEEPS date; x = date (datetime64). No leak rules apply (M8)."""
    n = min(MAX_WINDOW, len(ind))
    window = ind.iloc[-n:].copy()
    window["x"] = window["date"]
    return window.reset_index(drop=True)


def _missing_days(dates: pd.Series) -> list[str]:
    """Every calendar day between the first and last bar that has no bar (weekends/holidays)."""
    normalized = pd.DatetimeIndex(dates).normalize()
    full_range = pd.date_range(normalized.min(), normalized.max(), freq="D")
    present = set(normalized)
    return [d.strftime("%Y-%m-%d") for d in full_range if d not in present]


def build_discover_figure(window: pd.DataFrame, theme: Theme, ticker: str, name: str) -> go.Figure:
    fig = build_figure(window, theme)
    fig.update_layout(title=f"{ticker} · {name}")
    missing = _missing_days(window["x"])
    if missing:
        fig.update_xaxes(rangebreaks=[{"values": missing}])
    return fig
