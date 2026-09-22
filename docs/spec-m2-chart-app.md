# Implementation spec M2: indicators, chart and app skeleton

PRD: §4 R1, R2, M2; §3 constraints and design. Common rules: [spec-common.md](spec-common.md).
Result: `uv run gt app` serves the page "Spielen" on port 8537 with a random anonymous chart, a
header, a light/dark switch and "App beenden".

## 1. Files

| Create / change | Content |
|---|---|
| `pyproject.toml` | deps nicegui, plotly; dev pytest-asyncio; `asyncio_mode = "auto"` |
| `tests/conftest.py` | add `pytest_plugins = ["nicegui.testing.user_plugin"]` at the top (keep the socket block) |
| `.env.example` | add `GT_PORT=` |
| `src/app/config.py` | `port` (default 8537) |
| `src/app/indicators.py` | R1 |
| `src/app/theme.py` | tokens, `page_css()` |
| `src/app/chart.py` | `decision_window`, `build_figure`, `preset_ranges`, `apply_preset` |
| `src/app/ui/__init__.py`, `ui/root.py`, `ui/chart_panel.py`, `ui/play.py` | UI |
| `src/app/cli.py` | sub-command `app` |

## 2. Design

### 2.1 `indicators.py` (pure)

```python
SMA_FAST, SMA_SLOW = 50, 200
BB_N, BB_K = 20, 2.0
RSI_N = ATR_N = 14
INDICATOR_COLUMNS = ("sma50", "sma200", "bb_upper", "bb_mid", "bb_lower", "rsi14", "atr14")

def sma(close: pd.Series, n: int) -> pd.Series                      # rolling(n, min_periods=n).mean()
def bollinger(close: pd.Series, n: int = BB_N, k: float = BB_K
              ) -> tuple[pd.Series, pd.Series, pd.Series]           # (upper, mid, lower), std ddof=0
def rsi_wilder(close: pd.Series, n: int = RSI_N) -> pd.Series
def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, n: int = ATR_N) -> pd.Series
def with_indicators(bars: pd.DataFrame) -> pd.DataFrame            # copy + INDICATOR_COLUMNS
```

Wilder smoothing (D4), shared by RSI and ATR:

```python
def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    """x[0] is unused. out[i] = NaN for i < n; out[n] = mean(x[1:n+1]);
    out[i] = (out[i-1] * (n-1) + x[i]) / n for i > n. All NaN if len(x) <= n."""
```

- RSI: `diff = close.diff()`, gains = max(diff, 0), losses = max(−diff, 0); `ag`, `al` = `_wilder`.
  RSI = 100 if `al == 0 and ag > 0`; 50 if both are 0; else `100 − 100 / (1 + ag/al)`. Use
  `np.errstate(divide="ignore", invalid="ignore")` or masks; no warnings.
- ATR: `TR[i] = max(H_i − L_i, |H_i − C_{i−1}|, |L_i − C_{i−1}|)` for i ≥ 1, then `_wilder`.
- A simple Python loop in `_wilder` is fast enough (6,000 rows ≈ 3 ms).

### 2.2 `theme.py` (pure)

```python
@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    surface: str
    primary: str
    accent: str
    text: str
    up: str
    down: str
    grid: str      # addition: subtle grid (not in PRD table)
    muted: str     # addition: Bollinger and RSI guide lines

LIGHT = Theme("hell", "#E3EAF4", "#F4F7FB", "#5448E0", "#1FC1F0", "#1B1F4B", "#22B35E", "#E5484D",
              "#D3DCE8", "#8A93B2")
DARK = Theme("dunkel", "#0A1628", "#12233A", "#1E88E5", "#1FC1F0", "#E8EEF6", "#22B35E", "#E5484D",
             "#1E3350", "#7F8FA6")

def theme_for(is_dark: bool) -> Theme
def page_css() -> str
```

`page_css()` returns CSS built from the tokens (Quasar sets `body.body--dark` in dark mode):

```css
:root { --gt-bg: <LIGHT.background>; --gt-surface: …; --gt-text: …; --q-primary: <LIGHT.primary>; --q-accent: <LIGHT.accent>; }
body.body--dark { --gt-bg: <DARK.background>; …; --q-primary: <DARK.primary>; }
body { background: var(--gt-bg); color: var(--gt-text); font-family: system-ui, sans-serif; }
.gt-card { background: var(--gt-surface); border-radius: 22px; padding: 20px;
           box-shadow: 0 8px 24px rgba(27, 31, 75, .08); }
body.body--dark .gt-card { box-shadow: 0 8px 24px rgba(0, 0, 0, .35); }
.gt-header { background: var(--gt-surface) !important; color: var(--gt-text) !important; }
```

### 2.3 `chart.py` (plotly; pyright header from spec-common §4)

```python
MAX_WINDOW = 1260
PRESETS: dict[str, int] = {"3M": 63, "6M": 126, "1J": 252, "5J": 1260}
START_PRESET = "1J"
Y_PAD = 0.03
TRACE_NAMES = ("Kurs", "SMA50", "SMA200", "BB oben", "BB Mitte", "BB unten",
               "Volumen", "RSI14", "RSI 30", "RSI 70")

def decision_window(bars: pd.DataFrame, t0_idx: int) -> pd.DataFrame:
    """Rows max(0, t0_idx - 1259) .. t0_idx of a frame that already has indicators.
    Adds int column x = row - t0_idx (…, -1, 0) and DROPS the date column (leak-proof)."""

def build_figure(window: pd.DataFrame, theme: Theme) -> go.Figure:
def preset_ranges(window: pd.DataFrame, preset: str) -> tuple[tuple[float, float], tuple[float, float]]:
def apply_preset(fig: go.Figure, window: pd.DataFrame, preset: str) -> None:
```

**build_figure**

- `make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.15, 0.25])`.
- Row 1: `go.Candlestick` "Kurs" (increasing line and fill `theme.up`, decreasing `theme.down`);
  `go.Scatter` lines "SMA50" (`theme.accent`), "SMA200" (`theme.primary`), "BB oben", "BB Mitte",
  "BB unten" (`theme.muted`; upper and lower dashed, middle dotted).
- Row 2: `go.Bar` "Volumen", one colour per bar: `theme.up if close >= open else theme.down`.
- Row 3: "RSI14" (`theme.primary`), "RSI 30" and "RSI 70" as two-point `go.Scatter` lines from the
  first to the last x (`theme.muted`, dashed). They are traces, not shapes, because the acceptance
  test counts traces.
- Trace order = `TRACE_NAMES`. x = `window["x"]` everywhere. NaN values stay NaN; plotly leaves
  gaps (PRD edge case).
- `fig.update_yaxes(side="right", gridcolor=theme.grid)`, `fig.update_yaxes(range=[0, 100], row=3, col=1)`,
  `fig.update_xaxes(rangeslider_visible=False, gridcolor=theme.grid)`.
- `fig.update_layout(paper_bgcolor=theme.surface, plot_bgcolor=theme.surface, font_color=theme.text,
  hovermode="x unified", legend={"orientation": "h", "y": 1.02}, margin={"l": 10, "r": 10, "t": 30, "b": 10})`.
  No title, no dates, no ticker anywhere.
- Finally `apply_preset(fig, window, START_PRESET)`.

**preset_ranges**: `n = min(PRESETS[preset], len(window))`, `vis = window.tail(n)`,
`x_last = vis["x"].iloc[-1]` → x range `(x_last − n + 0.5, x_last + 0.5)`.
`lo = nanmin(vis.low, vis.bb_lower)`, `hi = nanmax(vis.high, vis.bb_upper)` → y range
`(lo · (1 − Y_PAD), hi · (1 + Y_PAD))`. SMA lines don't count (R2: candles and bands).

**apply_preset**: `fig.update_xaxes(range=list(x))` (all shared x axes);
`fig.update_yaxes(range=list(y), row=1, col=1)`.

### 2.4 UI

Structure (verified pattern for NiceGUI 3.17): one `root()` function, `ui.sub_pages` for routes. The
same `root` goes to `ui.run` and to `user_simulation` in tests.

```python
# ui/root.py
DETECT_DARK_JS = "window.matchMedia('(prefers-color-scheme: dark)').matches"

def root() -> None:
    ui.add_css(page_css())
    dark = ui.dark_mode(None).bind_value(nicegui_app.storage.general, "dark_mode")
    ui.timer(0, lambda: _resolve_system_theme(dark), once=True)
    _header(dark)
    ui.sub_pages({"/": lambda: play_page(dark)})          # M5 adds "/setup"

async def _resolve_system_theme(dark: ui.dark_mode) -> None:
    if dark.value is None:
        dark.set_value(cast(bool, await ui.run_javascript(DETECT_DARK_JS)))

def _header(dark: ui.dark_mode) -> None:
    # ui.header().classes("gt-header"): label "Gamified Trader", ui.link("Spielen", "/"),
    # spacer, button "Hell/Dunkel" -> dark.set_value(not bool(dark.value)),
    # button "App beenden" -> on_click=lambda: nicegui_app.shutdown()

def run_app(cfg: Config) -> None:
    ui.run(root, port=cfg.port, title="Gamified Trader", reload=False, show=False)
```

- `ui.dark_mode(None)`: the default is `False`, which would overwrite "follow the system" (verified).
- `from nicegui import app as nicegui_app`: the name `app` is our own package.
- The navigation shows only implemented pages: "Spielen" now, "Setup" from M5.

```python
# ui/chart_panel.py (reused in M6)
def chart_panel(window: pd.DataFrame, dark: ui.dark_mode) -> ui.plotly:
    """Preset buttons 3M/6M/1J/5J above a ui.plotly in a .gt-card.
    Button -> build a fresh figure with apply_preset(...) -> plot.update_figure(fig).
    dark.on_value_change(...) -> rebuild the figure with theme_for(dark.value is True),
    keep the current preset; return early if plot.is_deleted."""
```

```python
# ui/play.py (M2 version; M6 replaces the body)
def play_page(dark: ui.dark_mode) -> None:
    cfg = load_config()
    picked = pick_random_chart(PriceStore(cfg.prices_dir), random.Random())
    if picked is None:
        ui.label("Keine Kursdaten gefunden. Bitte zuerst `gt data download` ausführen.")
        return
    bars, t0_idx = picked
    chart_panel(decision_window(with_indicators(bars), t0_idx), dark)

def pick_random_chart(store: PriceStore, rng: random.Random) -> tuple[pd.DataFrame, int] | None:
    """Random ticker with >= 250 rows; t0_idx uniform in [249, len - 1]. None if none qualifies."""
```

### 2.5 CLI `gt app`

```python
def _cmd_app(cfg: Config) -> int:
    storage = cfg.data_dir / "nicegui"
    storage.mkdir(parents=True, exist_ok=True)   # NiceGUI's own mkdir has no parents=True
    os.environ.setdefault("NICEGUI_STORAGE_PATH", str(storage))
    from app.ui.root import run_app   # lazy: NiceGUI reads NICEGUI_STORAGE_PATH at import time
    run_app(cfg)
    return 0
```

The lazy import also keeps `gt data …` fast. `data/` is already gitignored. Verified on 2026-09-21:
started this way, the app serves the page and writes `data/nicegui/storage-general.json`. Without
the `mkdir`, the first theme write fails on a fresh clone with `FileNotFoundError`.

## 3. Tests

Reference values below are hand-calculated (exact fractions). Name them as such in the test
docstrings. Tolerance `pytest.approx(v, abs=1e-6)`.

| File | Test | Asserts |
|---|---|---|
| `test_indicators.py` | sma hand values | `sma(1..10, 3)` = `[nan, nan, 2, 3, …, 9]`; `sma(1..60, 50)[49] == 25.5` |
| | bollinger hand values | closes `[1, 2, 3, 4]`, n = 3: index 2 → mid 2, upper `2 + 2·sqrt(2/3)` = 3.632993161855452, lower 0.36700683814454793 |
| | bollinger constant | 25 × 5.0 → upper = mid = lower = 5.0 at index 19+, no warning |
| | rsi hand values | closes `[100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 105, 107, 106, 108, 107, 110, 106]` → indices 0–13 NaN; 14: 200/3; 15: 640/9; 16: 41600/697 |
| | rsi only gains → 100 | closes 1..30 → all values from index 14 are 100 |
| | rsi constant → 50 | |
| | rsi range | 20 seeded random walks (`random_walk_bars`) → every non-NaN value in [0, 100] |
| | atr hand values | high `[11,12,12,13,13,14,14,15,15,16,16,17,17,18,18,25,19]`, low `[9,10,10,11,11,12,12,13,13,14,14,15,15,16,16,20,17]`, close `[10,11,11,12,12,13,13,14,14,15,15,16,16,17,17,24,18]` → TR[1..14] = 2, TR[15] = 8 (gap up), TR[16] = 7 (gap down); ATR 14: 2; 15: 17/7; 16: 135/49 |
| | causality | seeds 0..19: `n = rng.integers(300, 700)`, `t = rng.integers(0, n)` → `with_indicators(b.iloc[:t+1])` equals `with_indicators(b).iloc[:t+1]` with `assert_frame_equal(check_exact=True)` |
| `test_theme.py` | tokens | LIGHT/DARK values equal the PRD table; `page_css()` contains both primary colours and `body.body--dark` |
| `test_chart.py` | structure | 400 bars, t0 = 399 → trace names == `TRACE_NAMES`; `fig.layout.yaxis3` exists, `yaxis4` does not; `yaxis.side == "right"`; `yaxis3.range == (0, 100)`; last x of "Kurs" == 0 |
| | window length | 1,500 bars, t0 = 1,499 → 1,260 candles; 300 bars → 300 |
| | SMA200 from first visible | 1,500 bars, t0 = 1,499 → `window.sma200.notna().all()` |
| | short history | 300 bars → the first 199 SMA200 values are NaN, the figure builds, JSON contains `null` |
| | no leak | `fig.to_json()` doesn't match `\d{4}-\d{2}-\d{2}`; `"date"` not in `window.columns` |
| | presets | window of 400 → for each preset, x range `(−n + 0.5, 0.5)` with n = min(preset, 400); y range = (min(low, bb_lower) · 0.97, max(high, bb_upper) · 1.03) of the last n rows; start preset = 1J |
| | theme colours | light: `paper_bgcolor == LIGHT.surface`, candle increasing line == `#22B35E`; dark: `DARK.surface` |
| | volume colours | a falling candle's bar colour == `theme.down` |
| | constant prices, volume 0 | builds without exception |
| `test_ui_shell.py` | page loads | `write_store` with 2 random-walk tickers of 400 bars → one `ui.plotly`; its `props["options"]` contains "SMA200" |
| | no data → hint | empty `GT_DATA_DIR` → should_see "gt data download" |
| | system dark resolved | JS rule → True → `eventually(storage.general["dark_mode"] is True)`; plot options contain `DARK.surface` |
| | toggle | then click "Hell/Dunkel" → stored False; plot options contain `LIGHT.surface` |
| | stored choice wins | set `storage.general["dark_mode"] = False` before `open` → stays False (JS rule would say True) |
| | shutdown | `MagicMock` on `nicegui_app.shutdown`; click "App beenden" → `assert_called_once()` |
| | preset button | click "3M" → `list(props["options"]["layout"]["xaxis"]["range"]) == [-62.5, 0.5]` |
| `test_cli_app.py` | port default and override | monkeypatch `nicegui.ui.run` with a recorder, `GT_DATA_DIR=tmp_path` and `NICEGUI_STORAGE_PATH` (so `setdefault` changes nothing) → `main(["app"])` returns 0; kwargs `port == 8537`, `reload is False`, `show is False`; `tmp_path/"nicegui"` exists; with `GT_PORT=8600` → 8600 |

`gt_user` fixture as in spec-common §5, plus a default JS rule
`user.javascript_rules[re.compile(".*prefers-color-scheme.*")] = lambda _m: False`; individual
tests override it.

## 4. Steps

1. Add nicegui, plotly, pytest-asyncio; set `asyncio_mode`; register the plugin in conftest. Write one
   trivial `user_simulation` test and get it green first (PRD risk "NiceGUI tests and offline rule").
   If it conflicts with the socket block, stop and ask. Don't loosen the block.
2. `indicators.py` (red → green).
3. `theme.py` (red → green).
4. `chart.py` (red → green). Run pyright: 0 errors with only the header.
5. `ui/root.py`, `ui/chart_panel.py`, `ui/play.py` (red → green).
6. `cli.py app` (red → green). Manual: `uv run gt app`, open `http://localhost:8537`.
7. Gate, docs.

## 5. Manual check

Chart and header are readable in light and dark and close to the reference images
(`docs/ui/references/`). Presets work; clicking a legend entry hides the trace; "App beenden" stops
the process. Report the result; the user compares against the references.

## 6. Pitfalls

- `ui.plotly` needs an explicit height: `.classes("w-full h-[640px]")`.
- Don't put the date column into the window, into `customdata` or into hover text.
- `dark.on_value_change` handlers survive sub-page navigation, hence the `plot.is_deleted` guard.
- Don't call `ui.run` at import time anywhere; only `run_app` calls it.
