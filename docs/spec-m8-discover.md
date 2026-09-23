# Implementation spec M8: Entdeckungsmodus

PRD: §4 R2, R4, R5, R9, R12–R14 (v0.6), M8; §5 A21, A22, A25, A26. Common rules:
[spec-common.md](spec-common.md). Builds on M7.1: [spec-m7-model.md](spec-m7-model.md),
[spec-m7-1-improve.md](spec-m7-1-improve.md).
Result: page "Entdecken" (`/entdecken`) loads any Yahoo ticker, shows a dated chart and, for stocks
with ≥ 250 bars, the R13 recommendation with a card for the active user.

## 1. Files

| Create / change | Kind | Content |
|---|---|---|
| `src/app/config.py` | core | `discover_dir` property (`data_dir / "discover"`) |
| `src/app/yahoo.py` | adapter | `fetch_history`, `fetch_quote_type` |
| `src/app/discover_store.py` | adapter | cache: bars via `PriceStore(discover_dir)`, `meta.json` read/write |
| `src/app/discover.py` | core | pure rules: ticker check, cache freshness, completed bars, analysis |
| `src/app/discover_service.py` | orchestration | wires cache, Yahoo, model bundle, pool features, `discover` |
| `src/app/chart.py` | core (plotly) | `discover_window`, `build_discover_figure`; date-aware `preset_ranges` |
| `src/app/ui/discover.py` | UI | page "Entdecken" |
| `src/app/ui/root.py` | UI | nav link "Entdecken", sub page `/entdecken` |
| `src/app/cli.py` | entry | `gt data download`/`update` rewrite `data/market.parquet` at the end |

No new dependency. No new environment variable.

## 2. Design

### 2.1 `yahoo.py` (adapter)

```python
def fetch_history(ticker: str) -> pd.DataFrame | None:
    """Full daily history (period="max"), normalized, uncleaned; None if Yahoo has nothing."""
    return fetch_batch([ticker], None).get(ticker)


def fetch_quote_type(ticker: str) -> str | None:
    """yf.Ticker(ticker).info.get("quoteType"), upper-cased; None on any exception or missing key."""
```

- `fetch_quote_type` catches `Exception` (Yahoo boundary; `info` raises on unknown symbols and rate
  limits). `fetch_history` doesn't catch: the service does (§2.4), so both failure kinds end up in
  one place.
- No retry/backoff in the UI path: `data_sync.call_with_retry` would add up to 14 s of sleeps to a
  page request. One attempt; on failure the service falls back to the cache.

### 2.2 `discover_store.py` (adapter)

```python
@dataclass(frozen=True)
class MetaEntry:
    fetched: date                 # calendar day of the last successful history fetch
    quote_type: str | None        # "EQUITY", "ETF", ... ; None = not determined yet

class DiscoverStore:
    def __init__(self, root: Path) -> None          # root = cfg.discover_dir
    def read_bars(self, ticker: str) -> pd.DataFrame | None     # PriceStore(root).read, None if absent
    def write_bars(self, ticker: str, df: pd.DataFrame) -> None # PriceStore(root).write (atomic)
    def meta(self, ticker: str) -> MetaEntry | None
    def set_meta(self, ticker: str, entry: MetaEntry) -> None   # read-modify-write meta.json, atomic
```

`meta.json`: `{"AAPL": {"fetched": "2026-09-23", "quote_type": "EQUITY"}, ...}`, written with
`indent=2, sort_keys=True` via tmp + `os.replace` (same pattern as `pool_store`). `PriceStore` is
reused for the parquet files, so the column contract and atomic write come for free. `data/prices/`
is never touched (A21) — `gt snapshots build` lists only `cfg.prices_dir`.

### 2.3 `discover.py` (core, pure)

```python
TICKER_RE = re.compile(r"^[A-Z0-9.\-^=]{1,20}$")
MIN_BARS = 250  # same threshold as R10's history requirement
DEFAULT_LEV_MID = 5  # L_mittel the model was trained with; Profi is never recommended (A22)
DEFAULT_FEE_TENTHS, DEFAULT_INTEREST_TENTHS = 20, 50
TOP_FEATURES = 5
SUGGESTION_SEP = " · "


class Status(StrEnum):
    OK = "ok"  # recommendation available
    TOO_SHORT = "too_short"  # < MIN_BARS completed bars
    NOT_EQUITY = "not_equity"  # quote_type != "EQUITY" (None counts as not equity)
    NO_MODEL = "no_model"  # model files missing
    MODEL_MISMATCH = "model_mismatch"  # meta["feature_columns"] != list(FEATURE_COLUMNS)
    MARKET_STALE = "market_stale"  # no market table, or its last row > 5 days before Tag 0


@dataclass(frozen=True)
class ModelBundle:
    models: Mapping[tuple[int, int, float], QuantileModel]  # ml.QuantileModel
    meta: Mapping[str, object]


@dataclass(frozen=True)
class FeatureInfo:
    name: str
    value: float | None  # None if NaN
    percentile: float | None  # share of pool values <= value, NaN-free; None if value is None


@dataclass(frozen=True)
class Analysis:
    ticker: str
    ind: pd.DataFrame  # completed bars with indicators (chart source)
    status: Status
    recommendation: Recommendation | None
    quantiles: dict[tuple[int, int], tuple[float, float, float]]  # empty unless OK
    top_features: list[FeatureInfo]  # empty unless OK
    beats_all: bool | None  # None unless a compatible model exists
```

Functions (each ≤ 50 lines, complexity ≤ 10):

- `suggestions(entries: Sequence[UniverseEntry]) -> list[str]`: `f"{e.ticker}{SUGGESTION_SEP}{e.name}"`.
- `normalize_ticker(text: str) -> str | None`: take the part before `SUGGESTION_SEP`, strip, upper;
  return it if `TICKER_RE.fullmatch`, else None. `".."` alone passes the regex but is harmless as a
  file stem only with a suffix — still reject any value consisting only of dots.
- `needs_fetch(entry: MetaEntry | None, today: date) -> bool`: `entry is None or entry.fetched < today`.
- `completed_bars(bars, today) -> pd.DataFrame`: rows with `date < today` (drops a possibly
  incomplete candle of today and anything later), index reset.
- `display_name(ticker) -> str`: `universe.ticker_names().get(ticker, ticker)` (no Yahoo name lookup).
- `beats_all(meta) -> bool`: `all(meta["beats_baselines"].values())` (A25; the artifact stores a
  dict per baseline: `never`, `k120_l1`, `k120_l5`).
- `model_matches(meta) -> bool`: `list(meta["feature_columns"]) == list(FEATURE_COLUMNS)`.
- `needs_model_hint(user: UserRow) -> bool`: `user.lev_mid != DEFAULT_LEV_MID` or fee/interest
  tenths differ from the defaults (A22).
- `market_fresh(market, tag0) -> bool`: `market` not None and not empty and
  `tag0 - market.index.max() <= pd.Timedelta(days=5)` (PRD M8). A market table newer than Tag 0 is
  fine: `with_market` takes the latest row ≤ Tag 0.
- `feature_row(ind, market) -> pd.DataFrame`: `with_market(compute_features(ind,
  signal_flags(ind)).iloc[[-1]], pd.Series([ind["date"].iloc[-1]]), market)` — the same functions as
  the M7.1 training (PRD M8 criterion); a 1-row frame with `FEATURE_COLUMNS` keeps sklearn's column
  names. Tag 0 is always `ind["date"].iloc[-1]`.
- `quantiles_for(models, row) -> dict[(L, H), (p25, p50, p75)]`: `ml.predict_quantiles(models, row)`,
  unwrapped to floats for row 0.
- `top_features(meta, row, pool_features) -> list[FeatureInfo]`: the first `TOP_FEATURES` keys of
  `meta["importance"]` (already sorted descending by M7); percentile over the NaN-free pool column.
- `analyze(ticker, ind, quote_type, bundle, market, pool_features) -> Analysis`, in this order:
  1. `len(ind) < MIN_BARS` → TOO_SHORT.
  2. `quote_type != "EQUITY"` → NOT_EQUITY.
  3. `bundle is None` → NO_MODEL; `not model_matches(bundle.meta)` → MODEL_MISMATCH.
  4. `not market_fresh(market, Tag 0)` → MARKET_STALE.
  5. else OK: `row = feature_row(ind, market)`, `quantiles_for` (6 pairs), `ml.recommend`,
     `top_features`, `beats_all`.

  The input `ind` is already `with_indicators(completed_bars(...))`; `analyze` never sees today's bar.

- `recommendation_card(rec, ind, user) -> tuple[Card, Setting] | None` (reuses `game.setting_for`
  and `trading.make_card`): None if `rec.option` is a W option, `user is None`,
  `k_locked(setting.balance, setting.start_capital)`, or `atr14` at Tag 0 is NaN/0. Otherwise
  `make_card(horizon, close[-1], atr14[-1], setting.balance, setting.leverage, setting.costs)`.
  The UI renders it with `game.card_lines`; a W recommendation uses `game.wait_lines`.

### 2.4 `discover_service.py` (orchestration)

```python
class DiscoverError(Exception):        # message is the German UI text
    pass

@dataclass(frozen=True)
class Loaded:
    bars: pd.DataFrame                 # cleaned, completed bars
    quote_type: str | None
    stale: bool                        # True: fetch failed, cached data shown
    data_as_of: date                   # last bar date

class DiscoverService:
    def __init__(self, cfg: Config, today: Callable[[], date] = date.today) -> None
    def load(self, ticker: str) -> Loaded                     # raises DiscoverError
    def analyze(self, ticker: str) -> tuple[Loaded, Analysis] # raises DiscoverError

def load_bundle(cfg: Config) -> ModelBundle | None            # module level, tests monkeypatch
def load_market(cfg: Config) -> pd.DataFrame | None           # module level, tests monkeypatch
def load_pool_features(cfg: Config) -> pd.DataFrame | None    # module level, tests monkeypatch
```

`load(ticker)`:

1. `store = DiscoverStore(cfg.discover_dir)`; `entry = store.meta(ticker)`; `today = self._today()`.
2. If `needs_fetch(entry, today)`: call `yahoo.fetch_history(ticker)` (by module attribute, per the
   spec-common CLI recipe) inside `try/except Exception`. A frame → `clean_prices`, `write_bars`,
   quote type (below), `set_meta(MetaEntry(today, quote_type))`. `None` or exception → fall back to
   cached bars with `stale=True`; no cache → `DiscoverError(f"Keine Kursdaten für {ticker} gefunden.")`.
3. Quote type: tickers in `universe.ticker_names()` are `"EQUITY"` without a call. Otherwise reuse
   `entry.quote_type` if not None, else call `yahoo.fetch_quote_type(ticker)` once per history fetch.
4. Return `Loaded(completed_bars(bars, today), ...)`. Empty after `completed_bars` →
   `DiscoverError(f"Keine abgeschlossenen Kerzen für {ticker}.")`.

`analyze(ticker)`: `loaded = self.load(ticker)`; `ind = with_indicators(loaded.bars)`;
`discover.analyze(ticker, ind, loaded.quote_type, load_bundle(cfg), load_market(cfg),
load_pool_features(cfg))`.
Invalid input never reaches the service: the UI calls `normalize_ticker` first.

Caching of the model and pool features, like `game_service._load_pool_entries`:
`functools.lru_cache(maxsize=2)` on private helpers keyed by `(str(path), mtime_ns)`, so a retrain
invalidates the cache and repeated requests don't reload joblib (warm path ≤ 1 s). `load_bundle`
returns None if `model.joblib` or `model.json` is missing; `load_market` returns None if
`market.parquet` is missing (`model_store.read_market`); `load_pool_features` returns None if
`features.parquet` is missing (then `top_features` percentiles are None, not an error).

**Market table refresh.** A helper `cli._refresh_market(cfg) -> None` runs at the end of
`_data_download` and `_data_update` (after the sync report is printed, before returning the exit
code): if `store.tickers()` is empty it does nothing (`market_frame` can't concat zero tickers);
otherwise `model_store.write_market(market.market_frame(store.tickers(), store.read),
cfg.market_parquet)` and print `f"Markttabelle bis {date_de(last)}"`. On the full store this adds
≈ 15 s to `gt data update`. It keeps Entdecken's market features as current as the price store
without retraining.

### 2.5 `chart.py`

```python
def discover_window(ind: pd.DataFrame) -> pd.DataFrame:
    """Last min(1260, len) rows; KEEPS date; x = date (datetime64). No leak rules apply (M8)."""


def build_discover_figure(window: pd.DataFrame, theme: Theme, ticker: str, name: str) -> Figure:
    """build_figure(window, theme) + title f"{ticker} · {name}" + date rangebreaks."""
```

- The trace builders already read `x` from `window["x"]`, so dates flow through unchanged.
- Rangebreaks remove days without a bar so candles stay contiguous: one rangebreak
  `{"values": [...]}` with every calendar day in `[first, last]` that has no bar, as ISO date
  strings (weekends and holidays; ≈ 550 values for 5 years). No `bounds=["sat", "mon"]`: crypto and
  some FX tickers have weekend bars, which a weekend bound would hide.
- `preset_ranges` becomes date-aware: if `window["x"]` is datetime, x range =
  `(vis.x.iloc[0] - 12 h, vis.x.iloc[-1] + 12 h)` as ISO strings; otherwise unchanged. y range logic
  is shared. Existing game figures keep relative x and all M2/M6 leak tests stay green.
- `decision_window` is not changed (it must keep dropping `date`).

### 2.6 `ui/discover.py` and `ui/root.py`

`root.py`: header link `ui.link("Entdecken", "/entdecken")` between "Spielen" and "Setup";
`"/entdecken": lambda: discover_page(ctx)` in `ui.sub_pages`.

Page structure (same card/tile style as M6, two panes at `lg` as in M6.1):

```
[Disclaimer-Banner: Lern-App, keine Anlageberatung]            (always, first element)
[Eingabe (autocomplete = suggestions)] [Laden]
[Hinweise: Fehler | Datenstand veraltet | Baseline | A22 | Setup]
+- Chart (chart_panel, presets) --------+  +- Empfehlung --------------------------+
| TICKER · Name, Datenstand TT.MM.JJJJ  |  | K30 · Mittel  (or "Warten 30 Tage")   |
|                                       |  | G, P25 / P50 / P75 of V               |
|                                       |  | card_lines / wait_lines               |
|                                       |  | Tabelle 6 × (L, H): G P25 P50 P75     |
|                                       |  | Top-5 Features: Wert, Perzentil       |
+---------------------------------------+  +---------------------------------------+
```

- `ui.input(autocomplete=suggestions(load_universe()))`; Enter (`.on("keydown.enter", …)`) or
  "Laden" triggers the load. Both verified in the `User` simulation (2026-09-23, NiceGUI 3.17.1).
- The page builds one `DiscoverService(ctx.cfg)` and reads `ctx.active_user()` on every load (settings
  may have changed in Setup meanwhile).
- The 6-row table shows per (L, H): `ml.growth_score(q)`, P25, P50, P75; the recommended row is marked.
- The load runs off the event loop: `await run.io_bound(service.analyze, ticker)` (NiceGUI's
  `run`; works in the `User` simulation, verified). While it runs, the button is disabled and a
  spinner shows. Results are rendered into a `ui.column` that is cleared before each load.
- Status → German text (constants in `ui/discover.py`):

| Case | Text |
|---|---|
| invalid input | „Ungültiges Tickersymbol." |
| `DiscoverError` | its message |
| `stale` | „Aktualisierung fehlgeschlagen – Datenstand {date_de}." |
| TOO_SHORT | „Weniger als 250 Kerzen – keine Empfehlung." |
| NOT_EQUITY | „Modell nur auf Aktien trainiert – keine Empfehlung." |
| NO_MODEL | „Kein Modell gefunden. Zuerst `gt model train` ausführen." |
| MODEL_MISMATCH | „Modell passt nicht zur Featureliste. `gt model train` erneut ausführen." |
| MARKET_STALE | „Marktdaten veraltet – `gt data update` ausführen." |
| `beats_all is False` | „Das Modell schlägt nicht jede einfache Vergleichsstrategie." plus a line with `growth_model` and each `growth_baselines` value in % per round |
| `needs_model_hint` | „Modell mit Hebel 1/5 und Standardkosten trainiert, die Karte nutzt Ihre Werte." |
| no user / locked | „Positionsgröße: zuerst im Setup einen Nutzer anlegen." / „Guthaben unter 1 % des Startkapitals – Reset im Setup." |

- Values: G, V and P25/P50/P75 via `fmt.pct`; dates via `fmt.date_de`; percentiles as `fmt.pct(p, signed=False)`.
- Mark elements for tests: `.mark("disclaimer")`, `.mark("ticker-input")`, `.mark("load")`,
  `.mark("recommendation")`, `.mark("quantile-table")`, `.mark("top-features")`, `.mark("hint")`.
- No booking, no DB writes, nothing about the recommendation is stored.

## 3. Tests

Synthetic data only; the network stays blocked. Fakes are injected by monkeypatching module
attributes: `yahoo.fetch_history`, `yahoo.fetch_quote_type`, `discover_service.load_bundle`,
`discover_service.load_market`, `discover_service.load_pool_features`, `universe.ticker_names`. A
fake `ModelBundle` uses constant predictors (like `test_ml_recommend._FakeModel`) and a meta dict
with `feature_columns`, `importance`, `beats_baselines`, `growth_model` and `growth_baselines` — no
sklearn training in M8 tests. A fake market table is a small frame with `MARKET_COLUMNS`.
UI tests wait for the `run.io_bound` result with `await user.should_see(text, retries=30)` (verified
pattern); type with `user.find(marker="ticker-input").type("AAPL")`, then click "Laden" or
`.trigger("keydown.enter")`.

| File | Test | Asserts |
|---|---|---|
| `test_discover.py` | `normalize_ticker` | `" aapl "` → `AAPL`; `"SAP.DE · SAP SE"` → `SAP.DE`; `^GSPC`, `EURUSD=X`, `BTC-USD` valid; `"../x"`, `"A B"`, `""`, `"..."`, 21 chars → None |
| | `needs_fetch` | None → True; fetched today → False; yesterday → True |
| | `completed_bars` | a bar dated today and one dated tomorrow are dropped; earlier bars kept |
| | `beats_all` | all True → True; one False → False |
| | `needs_model_hint` | defaults → False; `lev_mid` 3, `fee_tenths` 10 → True each; `lev_pro` 15 alone → False |
| | `market_fresh` | last row 5 days before Tag 0 → True; 6 days → False; None/empty → False |
| | `analyze` statuses | 249 bars → TOO_SHORT; quote_type "ETF" and None → NOT_EQUITY; no bundle → NO_MODEL; wrong feature list → MODEL_MISMATCH; stale market → MARKET_STALE; OK with fake bundle → recommendation matches `ml.recommend` on the fake quantiles (6 pairs) |
| | same features as M7.1 | the row passed to the models equals `with_market(compute_features(...))` of the last completed bar (spy model records its input) |
| | only bars up to Tag 0 | `analyze` on `completed_bars(bars + today's bar)` equals `analyze` on `bars` |
| | `top_features` | order from `meta["importance"]`; percentile hand-computed on a 4-row pool; NaN value → None |
| | `recommendation_card` | K + user → `make_card` values; W → None; no user → None; locked balance → None; ATR 0 → None |
| `test_discover_store.py` | round trip | bars and meta survive; meta keys sorted; no tmp files left; missing → None |
| `test_cli_data.py` (extend) | market refresh | after `data update` with a fake fetch, `market.parquet` exists and its last date equals the store's last date |
| `test_discover_service.py` | cache | fake clock: first `load` → 1 history fetch; second same day → 0; next day → 1 |
| | quote type | universe ticker → 0 `fetch_quote_type` calls; other ticker → 1 on first fetch, 0 on a same-day reload |
| | failures | fetch raises with cache → `stale=True`, cached data; fetch returns None without cache → `DiscoverError` with "Keine Kursdaten" |
| | pool untouched | after `load` of a new ticker, `PriceStore(cfg.prices_dir).tickers()` is unchanged and `cli.main(["snapshots", "build", ...])` pool tickers exclude it |
| | bundle cache | `load_bundle` twice → joblib loaded once; after touching `model.json` (new mtime) → reloaded |
| `test_yahoo.py` (extend) | `fetch_quote_type` | fake `yf.Ticker` with `info={"quoteType": "etf"}` → `"ETF"`; raising `info` → None; `fetch_history` returns the single ticker's frame or None |
| `test_chart.py` (extend) | discover figure | x values are dates; title has ticker and name; rangebreak values contain a weekend day and a removed weekday (holiday), and no day that has a bar; a 7-day-a-week series gets no rangebreak values; preset "3M" sets the x range to the last 63 bars' dates ± 12 h; game `build_figure` output is unchanged (existing leak test still green) |
| `test_ui_discover.py` | page | nav link present; disclaimer visible before and after a load |
| | invalid input | `"../x"` → „Ungültiges Tickersymbol.", zero adapter calls |
| | unknown ticker | fake history None → „Keine Kursdaten …" and no chart |
| | OK path | fake data + fake bundle → recommendation with G, quantile table (6 rows) and top-5 features rendered; a plotly element whose title contains the ticker |
| | hints | `beats_baselines` with one False → baseline hint with growth values; ETF → not-equity hint; no bundle → `gt model train` hint; stale market → `gt data update` hint; user with `lev_mid` 3 → A22 hint; no user → setup hint and no card |

Budget: the new tests add ≤ 5 s to the suite (no training, bars ≤ 1,600).

## 4. Steps (plan for the implementer)

Read only [spec-common.md](spec-common.md) and this file; open the PRD only for a cited rule. Set the
M8 row in IMPLEMENTATION.md to `in progress` first. Each step: write the tests of §3 for that step,
run them and see them fail for the stated reason, implement, run them green, then
`uv run pyright && uv run ruff check .` before the next step. Keep a red/green list for the summary.
Never run `ruff format .` on the whole repo (it rewrites Markdown code blocks); format single files.

| # | Step | Red reason | Verify |
|---|---|---|---|
| 1 | `config.discover_dir`; `discover.py` constants, `Status`, dataclasses, pure helpers (`normalize_ticker`, `display_name`, `needs_fetch`, `completed_bars`, `beats_all`, `model_matches`, `needs_model_hint`, `market_fresh`) | ImportError | `uv run pytest tests/test_discover.py tests/test_config.py` |
| 2 | `discover.py` `feature_row`, `quantiles_for`, `top_features`, `analyze`, `recommendation_card` | ImportError / AttributeError | `tests/test_discover.py` all green; spy test proves the M7.1 feature path |
| 3 | `yahoo.fetch_history`, `yahoo.fetch_quote_type`; `discover_store.py` | AttributeError / ImportError | `tests/test_yahoo.py tests/test_discover_store.py` |
| 4 | `discover_service.py`: `load`, `analyze`, `load_bundle`/`load_market`/`load_pool_features` with mtime-keyed `lru_cache` | ImportError | `tests/test_discover_service.py` incl. "pool untouched" |
| 5 | `cli._refresh_market` after `data download`/`update` | assertion (no `market.parquet`) | `tests/test_cli_data.py` |
| 6 | `chart.discover_window`, `build_discover_figure`, date-aware `preset_ranges` | AttributeError | `tests/test_chart.py` plus the untouched M2/M6 leak tests |
| 7 | `ui/discover.py`, link and sub page in `ui/root.py` | route/marker missing | `tests/test_ui_discover.py`, all `tests/test_ui_*.py` |
| 8 | Gate | — | `uv run pre-commit run --all-files`; suite ≤ 60 s (check `--durations=10` if close) |
| 9 | Docs | — | IMPLEMENTATION.md (phase row, module map, §4 notes), `docs/architecture.md` M8 data flow, README usage line; `uv run pytest tests/test_docs.py` |
| 10 | Manual (network, see below) | — | results in IMPLEMENTATION.md §4 |

Manual check: `uv run gt data update` (prints "Markttabelle bis …"), then `uv run gt app` and load
AAPL, SAP.DE, a stock outside the universe, SPY (ETF → not-equity hint) and `../x` (invalid). Time
cold and warm loads (budget ≤ 5 s / ≤ 1 s). Measured 2026-09-23 without network: model load 0.16 s
(warm OS cache; 0.8 s cold), features 0.06 s, predict + percentiles 0.05 s — Yahoo dominates the
cold path. A headless browser check of the two-pane layout is optional (Playwright was used for
M6.1). Stop the app with "App beenden", never by port.

Report at the end: red/green list, gate result, manual results, every decision the spec didn't cover.
Don't commit; the user runs `/commit-git`.

## 5. Pitfalls

- `yf.Ticker(...).info` is slow (≈ 1 s) and flaky: call it at most once per ticker per history fetch
  and never for universe tickers.
- Yahoo returns today's bar during trading hours with partial OHLC; `completed_bars` must run before
  indicators and features, otherwise the recommendation depends on the time of day.
- `clean_prices` before caching, so the cache honours the same `PriceStore` column contract as
  `data/prices/`.
- `PriceStore.path` only rejects `/`; `normalize_ticker` is the real guard against odd file names.
- Keep `decision_window` untouched; the discover chart gets its own window builder. The M2/M6 leak
  tests must stay green without edits.
- Import `ml.QuantileModel` (public since M7.1) for `ModelBundle`; never import `_`-names across
  modules (pyright `reportPrivateUsage`).
- Don't import sklearn in `discover.py`: the bundle's models only need `.predict`; `joblib.load`
  stays in `model_store.read_model`.
