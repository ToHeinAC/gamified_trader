# Implementation spec: common part (Release 1, M1–M6)

For the implementer (Claude Code, Sonnet, effort medium). Read this file and the spec of the current
milestone. Open [PRD.md](../PRD.md) only for the rule a spec section cites (R1–R11, M1–M6).
Rules: [AGENTS.md](../AGENTS.md). Milestone specs:
[M1](spec-m1-data.md) · [M2](spec-m2-chart-app.md) · [M3](spec-m3-trading.md) ·
[M4](spec-m4-pool.md) · [M5](spec-m5-setup.md) · [M6](spec-m6-game.md).

Priority when sources disagree: PRD > AGENTS.md > this spec. If a spec contradicts the PRD, stop and
report it. If a spec is silent, choose the simplest option and name it in the summary.

## 1. Decisions beyond the PRD

The PRD leaves these open. The specs follow the decision in the right-hand column. D13 goes beyond
the PRD and was approved by the user on 2026-09-22.

| ID | Topic | Decision |
|---|---|---|
| D1 | Money math (R4–R9) | `decimal.Decimal` throughout; floats enter via `Decimal(repr(x))`. Verified: the PRD worked example comes out exactly (see M3). |
| D2 | Rounding of d (R4) | Clamp first, then `quantize(Decimal("0.0001"), ROUND_HALF_UP)`. With L = 7, d can end up 0.1143 > 0.8/7; harmless, because P&L is floored at −M anyway. |
| D3 | KO level | `E·(1 − 1/L)` as an unrounded Decimal. |
| D4 | ATR/RSI seeding | TA-Lib convention: first value at index n = 14, seeded with the mean of the first 14 changes (RSI) or of TR[1..14] (ATR). TR starts at index 1. |
| D5 | Pool V reference | `v_l{L}_h{H}` uses B = 10,000.00 € (default start capital), g = 2 %, z = 5 %. Stored in `snapshots.json`. |
| D6 | "Zufallstage" (A12) | The 30 % part is drawn from eligible **non-signal** days, so the pool has exactly round(0.7·N) signal days when enough exist. |
| D7 | V when K options are locked (R9) | If B < 1 % of the start capital, V and points are computed with the start capital as B (B may be 0 and V = P&L/B would be undefined). Nothing is booked for W options anyway. |
| D8 | CLI exit code (M1) | 1 if no ticker succeeded and at least one failed; else 0. A rerun where every ticker is skipped exits 0. |
| D9 | "Optimal share" statistic (M6) | Share of confirmed rounds with 100 points. Neutral rounds count as not optimal. |
| D10 | Theme default | Stored value `None` means "follow the system". On first page load, JavaScript asks the browser for the system scheme and the answer is stored. After that the stored choice wins. |
| D11 | Theme storage | `nicegui_app.storage.general["dark_mode"]` (server-side JSON file under `GT_DATA_DIR/nicegui`). No storage secret is needed. |
| D12 | Property tests | Seeded `numpy.random.default_rng` loops, no Hypothesis: Hypothesis is MPL-2.0, which AGENTS.md §5.5 doesn't list. |
| D13 | `gt data update` after a split or dividend | Approved 2026-09-22. With `auto_adjust=True`, Yahoo re-adjusts old prices, so appended rows could sit on a different adjustment basis than the stored history. `update` fetches from the last stored date inclusive; if that day's close changed by more than 0.5 %, it reloads the ticker's full history. Details: [M1 §2.4](spec-m1-data.md). |
| D14 | Untyped-library header (M7) | `ml.py` and `model_store.py` ship no stubs for scikit-learn/joblib, same root cause as M2's plotly and M1's yahoo module. Extended the header convention (§4) to these two modules; each names its own reason and cites this row. |

## 2. Dependencies

Resolved on 2026-09-21 (Python 3.13, uv): nicegui 3.17.1, plotly 7.1.0, yfinance 1.7.0,
pandas 3.0.6, numpy 2.5.3, pyarrow 25.0.1, pandas-stubs 3.0.5, pytest-asyncio 1.4.0.

```bash
uv add yfinance pandas numpy pyarrow && uv add --dev pandas-stubs     # M1
uv add nicegui plotly && uv add --dev pytest-asyncio                  # M2
```

- Add each dependency in the milestone that first uses it. scikit-learn is not needed in Release 1.
- Licenses were checked for the whole resolved tree: every direct dependency is MIT, BSD or Apache-2.0.
  Three transitive packages are MPL-2.0 (certifi, bidict, orjson in dual-license); they are used
  unmodified. Report this to the user once; don't add workarounds.
- `uv.lock` must resolve for Python 3.11 and 3.14 (the CI matrix). Commit `uv.lock`.

## 3. Package layout (Release 1, final)

| Module | Milestone | Kind | Responsibility |
|---|---|---|---|
| `config.py` | M1 | core | `Config` dataclass from environment variables |
| `cleaning.py` | M1 | core | `clean_prices` (PRD M1 cleaning rules) |
| `universe.py` | M1 | adapter | read `resources/universe.csv` |
| `yahoo.py` | M1 | adapter | the only module that imports `yfinance` |
| `price_store.py` | M1 | adapter | `data/prices/<TICKER>.parquet` read/write |
| `data_sync.py` | M1 | core, injected I/O | download/update loop, retry, report |
| `cli.py` | M1+ | entry | `gt` (argparse) |
| `indicators.py` | M2 | core | R1 |
| `theme.py` | M2 | core | design tokens, CSS |
| `chart.py` | M2, M6 | core (plotly) | R2 figure, presets, preview and resolution overlays |
| `ui/root.py` | M2 | UI | `root()`, header, theme, `run_app()` |
| `ui/play.py` | M2 → M6 | UI | page "Spielen" |
| `trading.py` | M3 | core | R3–R9 |
| `signals.py` | M4 | core | R11 |
| `eligibility.py` | M4 | core | R10 |
| `pool.py` | M4 | core, injected I/O | candidate selection, pool rows, report |
| `pool_store.py` | M4 | adapter | `snapshots.parquet` and `snapshots.json` |
| `settings_rules.py` | M5 | core | input validation for Setup |
| `fmt.py` | M5 | core | German number and money formatting |
| `db.py` | M5, M6 | adapter | SQLite |
| `ui/setup.py` | M5 | UI | page "Setup" |
| `game.py` | M6 | core | drawing, card and resolution view models |
| `game_service.py` | M6 | orchestration | wires db, pool, prices and `game` |
| `resources/universe.csv` | M1 | data | ticker universe |

Delete `src/app/core.py` and `tests/test_core.py` in M1 (template example). In M1, also set
`name = "gamified-trader"` and a German one-line `description` in `pyproject.toml`, and add
`[project.scripts] gt = "app.cli:main"`.

## 4. Conventions

**Configuration** (`config.py`, M1; extend in later milestones)

```python
@dataclass(frozen=True)
class Config:
    data_dir: Path          # GT_DATA_DIR, default "data"
    port: int               # GT_PORT, default 8537 (M2)
    yahoo_pause_s: float    # GT_YAHOO_PAUSE_S, default 2.0

    @property
    def prices_dir(self) -> Path: ...        # data_dir / "prices"
    # M4: snapshots_parquet, snapshots_json; M5: db_path = data_dir / "app.db"

def load_config(env: Mapping[str, str] | None = None) -> Config: ...   # None -> os.environ
```

- Read the config at call time (in CLI handlers and page builders), never at import. Tests set
  `GT_DATA_DIR` with `monkeypatch.setenv`.
- List every key in `.env.example` without values.

**Money and numbers**

- Prices in DataFrames: float64. R4–R9 math: Decimal (D1). Helper `trading.dec(x: float) -> Decimal`
  returns `Decimal(repr(x))`. Never `Decimal(x)` on a float (it gives binary noise) and never float
  math for SL/TP: `103 * (1 - 0.05)` is `97.85` only by luck.
- `CENT = Decimal("0.01")`. SL: `ROUND_FLOOR`, TP: `ROUND_CEILING`, M: `ROUND_FLOOR`, G, F, P&L and
  card amounts: `ROUND_HALF_UP`.
- V is a float: `float(pnl / balance)`.
- SQLite stores money as integer cents, and rates as integer tenths of a percent (5.0 % → 50).
- UI shows amounts as `10.000,00 €` and percentages as `+1,60 %` (`fmt.py`, M5). Prices on cards
  and in the chart have no currency symbol.

**Typing (pyright strict in `src/`)**

- pandas is typed through `pandas-stubs`. NiceGUI ships types.
- plotly, yfinance, scikit-learn and joblib ship no stubs. Only `chart.py`, `yahoo.py`, `ml.py` and
  `model_store.py` may use them (D14), and each starts with a header of this shape (verified to give
  0 errors for plotly/yfinance; scikit-learn/joblib need two more flags, see `ml.py`):

```python
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# Reason: plotly/yfinance ship no type stubs; untyped calls stay inside this module (PRD §5 risks).
```

- UI modules don't import plotly. They take figures from `chart.py`, whose functions are annotated
  `-> go.Figure`.
- `await ui.run_javascript(...)` returns an unknown type: wrap it as `cast(bool, await ui.run_javascript(js))`.
- No other `# pyright: ignore`. If more seem necessary, stop and ask (PRD trigger: > 10 per module).

**pandas 3 pitfalls**

- A `DatetimeIndex` built from strings is `datetime64[us]`. Always pin the stored `date` column with
  `.astype("datetime64[ns]")`; the parquet round trip then keeps `ns`.
- Copy-on-write is the default, so chained assignment (`df["a"][mask] = x`) does nothing. Use `.loc`.
- Default string dtype is `str`. Compare string columns with `==`, not `is`.
- `rolling(...).mean()`, `.std(ddof=0)` and `.median()` are prefix-stable: values up to t don't change
  when rows after t are removed (verified). The causality tests rely on this.

**Code shape**

- Functions ≤ 50 lines, complexity ≤ 10: split UI builders into small functions per card or row.
- Pure modules get no `print`, file or network access. Adapters get no rule logic.
- `logging.getLogger(__name__)` for warnings (for example a skipped snapshot). No `print` outside `cli.py`.
- UI and CLI text is German. Identifiers, docstrings and comments are English.

## 5. Testing recipes

**Layout**: add an empty `tests/__init__.py` and a `tests/helpers.py` with shared factories.
`from tests.helpers import make_bars` then works in pytest and pyright (verified).

```python
# tests/helpers.py (M1; extend later)
def make_bars(closes: Sequence[float], *, start: str = "2001-01-02",
              spread: float = 0.01, volume: int = 1_000_000) -> pd.DataFrame:
    """Valid OHLCV frame on business days: open = previous close (first: close),
    high = max(open, close) * (1 + spread), low = min(open, close) * (1 - spread)."""

def random_walk_bars(n: int, seed: int, *, start_price: float = 50.0,
                     sigma: float = 0.02, start: str = "2001-01-02") -> pd.DataFrame:
    """closes = start_price * exp(cumsum(normal(0, sigma))) with default_rng(seed)."""

def write_store(root: Path, frames: Mapping[str, pd.DataFrame]) -> PriceStore: ...   # M1
```

Columns are always `date, open, high, low, close, volume` with dtypes datetime64[ns], float64 ×4, int64.

**NiceGUI UI tests** (verified with nicegui 3.17.1, pytest-asyncio 1.4.0 and the socket block):

```toml
# pyproject.toml [tool.pytest.ini_options] additions (M2)
asyncio_mode = "auto"
```

```python
# tests/conftest.py addition (M2): top of file
pytest_plugins = ["nicegui.testing.user_plugin"]   # session temp dir for app.storage; registers ini keys

# tests/test_ui_*.py
from nicegui.testing import User, user_simulation
from app.ui.root import root

@pytest.fixture
async def gt_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[User]:
    monkeypatch.setenv("GT_DATA_DIR", str(tmp_path))
    async with user_simulation(root=root) as user:
        yield user
```

- Use `user_simulation(root=root)`, not the plugin's `user` fixture: it needs no `main.py`, and
  NiceGUI globals are reset for each test.
- `await user.open("/")`, `await user.should_see("Text")`, `user.find("Button text").click()`,
  `user.find(ui.plotly).elements` (a set of elements).
- A plotly element's figure JSON is `element.props["options"]`.
- JavaScript answers are mocked with
  `user.javascript_rules[re.compile(r".*prefers-color-scheme.*")] = lambda _m: True`.
- Timers and awaited JavaScript run asynchronously. Poll for their effects with a helper, not a fixed sleep:

```python
async def eventually(check: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)
```

- Leak checks dump all rendered state (verified):

```python
def rendered_text(user: User) -> str:
    parts: list[str] = []
    for el in user.client.layout.descendants():
        parts.append(json.dumps(el.props, default=str))
        parts.append(str(getattr(el, "text", "")))
    return "\n".join(parts)
```

- Mock `app.shutdown` with `monkeypatch.setattr(nicegui_app, "shutdown", MagicMock())` before
  `user.open`. The button must call it via `lambda: nicegui_app.shutdown()`, so the lookup happens at
  click time.

**Other recipes**

- Fake time: pass `sleep: Callable[[float], None]` into the code under test. The test passes
  `sleeps.append` and asserts the list. Never really sleep in tests.
- CLI: call `cli.main([...])` and assert on the return code and on `capsys.readouterr().out`.
  Monkeypatch module attributes (`monkeypatch.setattr(yahoo, "fetch_batch", fake)`); `cli.py` must
  call them as `yahoo.fetch_batch(...)`, not import the function by name.
- Budget: the whole suite ≤ 60 s. Pool builds in tests use N ≤ 200 and ≤ 6 tickers with ≤ 1,600 bars.

## 6. Workflow per milestone

1. Set the phase row in [IMPLEMENTATION.md](../IMPLEMENTATION.md) to `in progress`.
2. Work through the milestone spec's steps in order. Each step: write the tests, run
   `uv run pytest tests/test_<x>.py -q`, and confirm they fail for the expected reason (ImportError for
   a missing module counts). Then implement until they pass. Note the red and green outcome for each
   test file in a short list; the final summary needs it.
3. The Stop hook runs the full gate whenever `.py` files changed, and blocks the stop if it fails.
   Never end a turn with deliberately failing tests.
4. Gate: `uv run pre-commit run --all-files`. Coverage ≥ 85 % branch.
5. Docs: run `/documentation-update`: module map, phase row `done` (after the manual checks, or note
   them as pending), `docs/architecture.md` data flow, README commands.
6. Ask the user to run `/commit-git` (only the user can invoke it). Never push.

Report at the end: the red/green list, the gate result, manual checks done or pending, and every
place where you had to decide something the spec didn't cover.
