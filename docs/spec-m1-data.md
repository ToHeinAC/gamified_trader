# Implementation spec M1: price data and universe

PRD: §4 M1. Common rules: [spec-common.md](spec-common.md) (read first).
Result: `gt data download` and `gt data update` fill `data/prices/*.parquet` from Yahoo; the universe
ships as `src/app/resources/universe.csv`.

## 1. Files

| Create / change | Content |
|---|---|
| `pyproject.toml` | name, description, `[project.scripts] gt = "app.cli:main"`, dependencies (spec-common §2) |
| `.env.example` | `GT_DATA_DIR=`, `GT_YAHOO_PAUSE_S=` |
| `src/app/core.py`, `tests/test_core.py` | delete |
| `src/app/config.py` | spec-common §4 (without `port` until M2) |
| `src/app/cleaning.py` | `clean_prices` |
| `src/app/yahoo.py` | `fetch_batch`, `split_download`, `normalize_frame` |
| `src/app/price_store.py` | `PriceStore` |
| `src/app/data_sync.py` | `call_with_retry`, `download`, `update`, `SyncReport` |
| `src/app/universe.py` | `UniverseEntry`, `load_universe` |
| `src/app/resources/universe.csv` | ≥ 600 rows |
| `src/app/cli.py` | `main(argv)`: `data download`, `data update` |
| `tests/__init__.py`, `tests/helpers.py` | spec-common §5 |
| `docs/data.md` | universe source, reference date, counts, conversion rules, data layout |

## 2. Design

### 2.1 `cleaning.py` (pure)

```python
PRICE_COLUMNS = ("open", "high", "low", "close")
COLUMNS = ("date", "open", "high", "low", "close", "volume")

@dataclass(frozen=True)
class CleanStats:
    rows_in: int
    dropped_invalid: int      # NaN in OHLC or any OHLC <= 0
    dropped_duplicates: int   # duplicate dates, the last row is kept
    high_fixed: int
    low_fixed: int

    @property
    def corrections(self) -> int: return self.high_fixed + self.low_fixed

def clean_prices(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleanStats]:
```

Input: columns `COLUMNS`, any row order, `volume` may be NaN. Steps in this order:

1. `volume` NaN → 0.
2. Drop rows with NaN in any of `PRICE_COLUMNS` or any value ≤ 0 there.
3. `drop_duplicates("date", keep="last")`: last in **input order**, before sorting.
4. `sort_values("date", kind="stable")`, reset the index.
5. `high = max(high, open, close)`, `low = min(low, open, close)`. Count changed rows separately.
6. dtypes: `date` datetime64[ns], OHLC float64, `volume` int64 (round first). Column order `COLUMNS`.

### 2.2 `yahoo.py` (adapter, the only `yfinance` import; pyright header from spec-common §4)

```python
def fetch_batch(tickers: Sequence[str], start: date | None) -> dict[str, pd.DataFrame]:
    """One yf.download call. Returns normalized, uncleaned frames; empty tickers are absent."""

def split_download(raw: pd.DataFrame, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
def normalize_frame(sub: pd.DataFrame) -> pd.DataFrame:
```

- Call: `yf.download(list(tickers), auto_adjust=True, actions=False, group_by="ticker",
  threads=False, progress=False, multi_level_index=True, **kw)`, where `kw = {"period": "max"}` if
  `start is None`, else `{"start": start.isoformat()}`. It can return `None`: treat that as empty.
- yfinance 1.7 never raises per ticker inside `download`: it logs the error and returns an empty or
  NaN block. Rate limits therefore show up as empty results (handled in `data_sync`, §2.4).
- `split_download` must accept all three shapes, because the acceptance test compares them:
  1. flat columns `Open, High, Low, Close, Volume` (one ticker),
  2. MultiIndex `(Ticker, Price)` (`group_by="ticker"`),
  3. MultiIndex `(Price, Ticker)` (`group_by="column"`).
  For a MultiIndex, find the level whose values contain the requested tickers, then use
  `raw.xs(t, axis=1, level=level)`. Omit a ticker whose `close` is all NaN.
- `normalize_frame`: lower-case the column names, keep `open, high, low, close, volume` (a missing
  `volume` becomes NaN). Index → `date` column: drop a timezone with `tz_localize(None)` (keeps the
  local exchange date), then `.normalize()` and `.astype("datetime64[ns]")`. Drop rows whose four
  prices are all NaN.

### 2.3 `price_store.py` (adapter)

```python
class PriceStore:
    def __init__(self, root: Path) -> None: ...
    def path(self, ticker: str) -> Path        # root / f"{ticker}.parquet"; ValueError on "" or "/"
    def has(self, ticker: str) -> bool
    def tickers(self) -> list[str]             # sorted file stems
    def read(self, ticker: str) -> pd.DataFrame
    def write(self, ticker: str, df: pd.DataFrame) -> None
    def last_date(self, ticker: str) -> date | None
```

- `write`: `mkdir(parents=True, exist_ok=True)`, write `<ticker>.parquet.tmp` with `index=False`,
  then `os.replace` (atomic). A file therefore always holds a complete history; restartability
  relies on this.
- `write` raises `ValueError` unless the columns are exactly `COLUMNS` and the dates are strictly ascending.

### 2.4 `data_sync.py` (core logic, I/O injected)

```python
FetchFn = Callable[[Sequence[str], date | None], dict[str, pd.DataFrame]]
SleepFn = Callable[[float], None]
BATCH_SIZE = 50
RETRIES = 3
BASE_DELAY_S = 2.0

class EmptyBatchError(RuntimeError): ...

def call_with_retry(fn: Callable[[], T], sleep: SleepFn,
                    retries: int = RETRIES, base_delay_s: float = BASE_DELAY_S) -> T:
    """Up to 1 + retries attempts; sleeps base * 2**k (2, 4, 8 s) between them; re-raises the last error."""

@dataclass
class SyncReport:
    mode: str                                   # "download" | "update"
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # ticker -> reason
    skipped: list[str] = field(default_factory=list)
    rows: int = 0
    corrections: int = 0
    dropped: int = 0                            # dropped_invalid + dropped_duplicates

    def exit_code(self) -> int: ...             # D8
    def render(self) -> str: ...                # German, see below

def download(tickers: Sequence[str], store: PriceStore, fetch: FetchFn, sleep: SleepFn,
             pause_s: float, batch_size: int = BATCH_SIZE) -> SyncReport:
def update(store: PriceStore, fetch: FetchFn, sleep: SleepFn,
           pause_s: float, batch_size: int = BATCH_SIZE) -> SyncReport:
```

**download**

1. `skipped` = tickers already in the store. `todo` = the rest, in input order.
2. For each batch of `todo`: `frames = call_with_retry(lambda: fetch_nonempty(batch), sleep)`, where
   `fetch_nonempty` raises `EmptyBatchError` if `fetch(batch, None)` returns no frame at all (the
   typical rate-limit symptom). If the call still fails after retries, mark every ticker of the batch
   failed with `repr(error)`, or with `"keine Daten"` for `EmptyBatchError`.
3. For each ticker: no frame, or empty after cleaning → failed `"keine Daten"`. Otherwise clean,
   write, add it to `succeeded`, and add rows, corrections and dropped to the totals.
4. `sleep(pause_s)` between batches (not after the last one).

**update**

1. Tickers = `store.tickers()`. Per batch: `start = min(last_date) + 1 day`;
   `frames = call_with_retry(lambda: fetch(batch, start), sleep)`, with no empty check, because
   "no new day" is normal.
2. Per ticker: clean the new frame, keep rows with `date > last_date(ticker)`, append them to the
   stored frame, write. A missing or empty frame is a success with 0 rows. A batch exception after
   retries → the batch's tickers fail.
3. Pause between batches as in download.

**render** (example):

```
gt data download: 648 erfolgreich, 12 fehlgeschlagen, 20 übersprungen
Zeilen: 3912114 · Korrekturen: 57 · entfernte Zeilen: 311
Fehlgeschlagen:
  ABC: keine Daten
```

### 2.5 `universe.py` (adapter) and `universe.csv`

```python
MARKETS = ("SP500", "NASDAQ100", "DAX", "MDAX", "SDAX")   # also the dedup priority

@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    name: str
    market: str

def load_universe() -> list[UniverseEntry]:   # importlib.resources.files("app") / "resources" / "universe.csv"
```

Building the CSV is a one-off manual step. Don't add a script or dependency to the repo:

1. In the session scratchpad, write a throwaway script and run it with
   `uv run --no-project --with pandas --with lxml --with requests python build_universe.py`.
   Send a browser-like `User-Agent` header, then `pd.read_html(io.StringIO(html))`.
2. Sources (current constituents, English Wikipedia): `List_of_S%26P_500_companies`, `Nasdaq-100`,
   `DAX`, `MDAX`, `SDAX`. Pick the table that has a ticker or symbol column. Expected counts are
   about 503, 101, 40, 50 and 70. If a page has no usable table, use the German Wikipedia page for that
   index and name it in `docs/data.md`.
3. Conversions: US `.` → `-` (`BRK.B` → `BRK-B`); German symbols get `.DE` unless they already have
   a suffix; strip whitespace; upper-case. Dedup by ticker, keeping the first market in `MARKETS`
   order.
4. Write with the `csv` module (quotes names that contain commas), with header `ticker,name,market`.
5. Spot-check 5 German tickers by hand with `uv run python -c "import yfinance as yf; ..."`. Fix any
   Yahoo symbol that differs (for example Porsche SE `PAH3.DE`) and list the fixes in `docs/data.md`.

### 2.6 `cli.py`

```python
def main(argv: Sequence[str] | None = None) -> int:
```

- argparse with sub-commands `data download [--tickers T [T ...]]` and `data update`. Without
  `--tickers`, the universe is used. Unknown tickers are allowed.
- The handler loads `Config`, builds `PriceStore(cfg.prices_dir)`, calls
  `data_sync.download(..., fetch=yahoo.fetch_batch, sleep=time.sleep, pause_s=cfg.yahoo_pause_s)`,
  prints `report.render()`, and returns `report.exit_code()`.
- Look up `yahoo.fetch_batch` and `time.sleep` at call time, so tests can monkeypatch them.

## 3. Tests (write each file before its module)

| File | Test | Asserts |
|---|---|---|
| `test_config.py` | defaults, env override | `data_dir == Path("data")`, `yahoo_pause_s == 2.0`; overrides are read from the mapping |
| `test_cleaning.py` | drops invalid rows | a NaN open, a close ≤ 0 and a low = 0 are removed; `dropped_invalid == 3` |
| | duplicate keeps last | two rows for the same date → the values of the later input row survive |
| | unsorted → sorted | ascending output; index 0..n−1 |
| | high/low corrected | high < max(open, close) → high = max; low > min → low = min; counts 1/1 |
| | volume NaN → 0 | dtype int64 |
| | dtypes and column order | exactly `COLUMNS`, datetime64[ns]/float64/int64 |
| `test_yahoo.py` | three shapes, same result | monkeypatch `yahoo.yf.download` to return shape 1, 2 and 3 (§2.2) built from the same numbers, with a tz-aware index `America/New_York` → after `clean_prices` and a `PriceStore` round trip the frames are equal (`pd.testing.assert_frame_equal`), dtypes included |
| | NaN ticker omitted | a batch with an all-NaN block for "BBB" → no "BBB" key |
| | `None` response | → `{}` |
| | period vs start | fake records kwargs: `period="max"` without start; `start="2024-01-03"` with start |
| `test_price_store.py` | write/read round trip, `last_date`, `tickers()` sorted, `has` | |
| | atomic write | no `.tmp` file remains; `write` of unsorted dates → `ValueError` |
| | bad ticker | `path("")` and `path("A/B")` → `ValueError` |
| `test_data_sync.py` | retry then success | fn raises twice, then returns → result returned; sleeps `[2.0, 4.0]` |
| | retry exhausted | raises 4× → re-raised; sleeps `[2.0, 4.0, 8.0]` |
| | failing ticker doesn't stop the run | fake returns data for AAA, nothing for BBB → AAA succeeded, BBB failed "keine Daten", exit 0 |
| | whole batch raises | batch_size 1: batch 1 raises every time, batch 2 fine → first ticker failed with the repr, second succeeded |
| | all failed → exit 1 | |
| | all skipped → exit 0 | (D8) |
| | empty batch is retried | fake returns `{}` 4× → sleeps `[2.0, 4.0, 8.0]`, all failed "keine Daten" |
| | pause between batches | 3 tickers, batch_size 1, pause 1.5 → sleeps `[1.5, 1.5]` |
| | restart skips complete tickers | AAA in store → fake called only with `["BBB"]`; AAA in `skipped` |
| | update appends only new days | store up to D; fake returns D−1…D+2 → file has D+1, D+2 appended; fake got `start == D + 1 day` |
| | update without new rows | fake returns `{}` → succeeded, 0 rows, no retries (sleeps `[]`) |
| | report counts | rows, corrections, dropped add up; `render()` contains "erfolgreich" and the failed ticker |
| `test_universe.py` | no duplicate tickers, no empty fields, ≥ 600 rows, markets ⊆ `MARKETS`, DAX/MDAX/SDAX tickers end with `.DE`, tickers upper-case without spaces | |
| `test_cli_data.py` | download with `--tickers` | monkeypatch `yahoo.fetch_batch` and `time.sleep`, `GT_DATA_DIR=tmp_path` → return code 0, parquet exists, "erfolgreich" in output |
| | all fail → return code 1 | |
| | update | store prepared with `write_store` → return code 0 |

Build the synthetic frames with `tests.helpers.make_bars`. No test touches the network.

## 4. Steps

1. Project setup: pyproject (name, script, deps), delete the template example, `tests/__init__.py`,
   `tests/helpers.py` (`make_bars`, `random_walk_bars`) → verify: `uv run pytest -q` green.
2. `config.py` (red → green).
3. `cleaning.py` (red → green).
4. `price_store.py`, then `write_store` in helpers (red → green).
5. `yahoo.py` (red → green). Check with pyright that the header is the only concession.
6. `data_sync.py` (red → green).
7. `universe.csv` (§2.5), `universe.py`, `docs/data.md` (red → green).
8. `cli.py` (red → green). `uv run gt --help` shows the commands.
9. Gate, docs, then the manual check below.

## 5. Manual check (outside the gate)

`uv run gt data download` for the full universe. It runs sequentially, about 10–20 minutes.
Success rate ≥ 95 %. Put the date, success count, failure count and the failed tickers (or how many)
into `IMPLEMENTATION.md` §4. If > 5 % fail, rerun once (it resumes); if still > 5 %, report to the
user (PRD risk trigger). Then run `uv run gt data update` once, which should add 0–1 rows per ticker.

## 6. Pitfalls

- yfinance upper-cases tickers internally: keep the universe upper-case so keys match.
- Don't retry on "empty" in `update` (§2.4), or every run on a trading-free day would wait 14 s per batch.
- Only split and normalize in `yahoo.py`. Cleaning and counting belong in `cleaning.py`.
- `data/` is gitignored; tests use `tmp_path` only.
