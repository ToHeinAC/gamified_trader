# Implementation spec M4: snapshot pool (50,000)

PRD: §4 R10, R11, M4. Common rules: [spec-common.md](spec-common.md) (D5, D6).
Result: `gt snapshots build --n 50000 --seed 42` writes `data/snapshots.parquet` and
`data/snapshots.json`.

## 1. Files

| Create / change | Content |
|---|---|
| `src/app/config.py` | `snapshots_parquet`, `snapshots_json` properties |
| `src/app/eligibility.py` | R10 mask per ticker |
| `src/app/signals.py` | R11 flags per ticker |
| `src/app/pool.py` | candidates, selection, rows, report, `build_pool` |
| `src/app/pool_store.py` | write/read parquet + json |
| `src/app/cli.py` | `snapshots build` |
| `tests/helpers.py` | `bars_with_gap`, small-pool factory |

## 2. Design

All per-ticker work is vectorized over every day of that ticker. The full history of a ticker is
the input; values at day t depend only on rows ≤ t (causal), except the explicitly future-looking
R10 conditions (≥ 120 bars after, no gap up to t0 + 120).

### 2.1 `signals.py` (pure)

```python
EVENTS = ("GOLDEN_CROSS", "DEATH_CROSS", "SMA200_UP", "SMA200_DOWN", "RSI_LT_30", "RSI_GT_70",
          "CLOSE_GT_UPPER_BB", "CLOSE_LT_LOWER_BB", "VOLUME_SPIKE")
EVENT_LABELS: dict[str, str]   # German text for M6, e.g. "Golden Cross: SMA50 kreuzt SMA200 aufwärts"
CROSS_LOOKBACK = 3

def cross_up(a: pd.Series, b: pd.Series) -> pd.Series     # a[t-1] <= b[t-1] and a[t] > b[t]; NaN -> False
def cross_down(a: pd.Series, b: pd.Series) -> pd.Series   # a[t-1] >= b[t-1] and a[t] < b[t]
def recent(x: pd.Series, k: int = CROSS_LOOKBACK) -> pd.Series   # x[t] | x[t-1] | x[t-2]
def signal_flags(ind: pd.DataFrame) -> pd.DataFrame:
    """Input: bars with indicators (M2). Output: one bool column 'sig_<EVENT>' per event,
    plus 'is_signal_day' = any. Same index as the input."""
```

- Crossings: GOLDEN/DEATH = recent(cross_up/down(sma50, sma200)); SMA200_UP/DOWN =
  recent(cross_up/down(close, sma200)).
- States at t: `rsi14 < 30`, `rsi14 > 70`, `close > bb_upper`, `close < bb_lower`,
  `volume > 2 * volume.rolling(20, min_periods=20).mean().shift(1)` (SMA20 up to day −1).
- Comparisons with NaN yield False; cast with `.fillna(False).astype(bool)` where needed.

### 2.2 `eligibility.py` (pure)

```python
MIN_DATE = pd.Timestamp("2000-01-01")
MIN_HISTORY = 250          # bars up to and including t0
FUTURE = 120
GAP_WINDOW_BACK = 250
MAX_GAP_DAYS = 10
MIN_CLOSE = 1.0
MIN_MEDIAN_TURNOVER = 1_000_000.0
TURNOVER_WINDOW = 20
MIN_SPACING = 20

def eligible_mask(ind: pd.DataFrame) -> np.ndarray:   # bool per row
```

Row i is eligible iff all of these hold:

1. `date[i] >= MIN_DATE`
2. `i >= MIN_HISTORY - 1` and `i <= len - 1 - FUTURE`
3. no gap: `bad[j] = (date[j] - date[j-1]).days > MAX_GAP_DAYS` for j ≥ 1; with `cb = cumsum(bad)`,
   the count over j ∈ [max(1, i − 249), i + 120] must be 0. Use the cumsum difference, not a loop.
4. `close[i] >= MIN_CLOSE`
5. `(close * volume).rolling(20, min_periods=20).median()[i] >= MIN_MEDIAN_TURNOVER`
6. `atr14[i] > 0` (NaN → False)

The spacing rule (≥ 20 bars between snapshots of one ticker) is enforced during selection (§2.3).

### 2.3 `pool.py` (pure core, I/O injected)

```python
LEVELS = (1, 5, 10)
REFERENCE_BALANCE = Decimal("10000.00")   # D5
SIGNAL_SHARE = 0.7
LoadFn = Callable[[str], pd.DataFrame]    # ticker -> cleaned bars (PriceStore.read)

@dataclass(frozen=True)
class TickerCandidates:
    ticker: str
    idx: np.ndarray          # eligible row indices
    is_signal: np.ndarray    # bool, same length

def ticker_candidates(ticker: str, bars: pd.DataFrame) -> TickerCandidates:
def select(cands: Sequence[TickerCandidates], n: int, seed: int
           ) -> tuple[list[tuple[str, int]], list[str]]:          # (ticker, idx) pairs, report notes
def snapshot_id(ticker: str, t0: pd.Timestamp) -> str             # sha1(f"{ticker}|{t0:%Y-%m-%d}")[:12]
def snapshot_row(ticker: str, ind: pd.DataFrame, flags: pd.DataFrame, i: int) -> dict[str, object]:
def build_pool(tickers: Sequence[str], load: LoadFn, n: int, seed: int) -> tuple[pd.DataFrame, dict[str, object]]:
class InsufficientSnapshotsError(ValueError): ...   # message: f"benötigt {n}, verfügbar {k}"
```

**Selection (`select`)**, deterministic for the same input and seed:

1. Concatenate all candidates in sorted-ticker order into arrays `(ticker_no, idx, is_signal)`.
2. `order = np.random.default_rng(seed).permutation(len)`.
3. Targets: `n_sig = round(SIGNAL_SHARE * n)`, `n_other = n - n_sig`.
4. Pass A: walk `order` and accept signal candidates until `n_sig` are accepted. Pass B: accept
   non-signal candidates until `n_other` (D6). Pass C, only if the total is still short: accept the
   remaining signal candidates.
5. Accept means: no accepted snapshot of the same ticker with `|idx − other| < MIN_SPACING`. Keep a
   sorted list per ticker and check both neighbours with `bisect`.
6. If Pass A ended short, add the note `"Nur {k} Signaltage verfügbar (Ziel {n_sig})."`. If the total
   is still < n, raise `InsufficientSnapshotsError(n, total)`.

**Row** (`snapshot_row`), one dict per snapshot:

| Column | Value |
|---|---|
| `snapshot_id` | `snapshot_id(ticker, date[i])` |
| `ticker` | str |
| `t0` | `date[i]` (datetime64[ns]) |
| `n_hist` | `i + 1` |
| `sig_<EVENT>` ×9, `is_signal_day` | from `flags.iloc[i]` |
| `v_l{L}_h{H}` | float V of the K option: `make_card(H, close[i], atr14[i], REFERENCE_BALANCE, L, DEFAULT_COSTS)`, `simulate` on bars i+1 .. i+H |
| `exit_l{L}_h{H}` | `result.reason.value` (TP, SL, KO, TIME) |
| `exit_day_l{L}_h{H}` | `result.exit_day` |
| `label_l{L}` | `trading.label(option_values(results, REFERENCE_BALANCE))` |

Pass the future as `ind[["open","high","low","close"]].iloc[i+1:i+121].to_numpy().tolist()` once
and reuse it for all 9 simulations.

**`build_pool`**

1. Phase 1: for each ticker (sorted): `load` → `with_indicators` → `ticker_candidates`. Keep only
   the small arrays, not the frames (memory: ~680 tickers × 6,000 rows).
2. Phase 2: `select`.
3. Phase 3: group the selection by ticker; `load` + `with_indicators` + `signal_flags` again, and
   build the rows.
4. DataFrame sorted by `(ticker, t0)`, index reset; dtypes: str columns as `str`, `t0`
   datetime64[ns], ints int64, flags bool, `v_*` float64.
5. Report dict (goes into the json and the CLI output):
   `n`, `seed`, `data_as_of` (max date over all loaded bars, ISO), `fee_rate` 0.02,
   `interest_rate` 0.05, `levels` [1, 5, 10], `reference_balance` 10000.0, `signal_share`
   (actual), `n_tickers`, `period` [min t0, max t0], `label_counts` {"l1": {label: count}, …},
   `tickers_without_snapshots` (sorted list), `notes`.

### 2.4 `pool_store.py` (adapter)

```python
def write_pool(df: pd.DataFrame, report: Mapping[str, object], parquet: Path, meta: Path) -> None
def read_pool(parquet: Path) -> pd.DataFrame
def read_meta(meta: Path) -> dict[str, object]
```

`df.to_parquet(parquet, index=False)`; the json is written with `indent=2, sort_keys=True,
ensure_ascii=False`. Both writes are atomic (tmp + `os.replace`). Parquet bytes are deterministic for
identical frames (verified with pyarrow 25), so never write a build timestamp into the parquet.

### 2.5 CLI

`gt snapshots build [--n 50000] [--seed 42]`: tickers = `store.tickers()`,
`load = store.read`. On success, print a German report (label distribution per level, signal share,
number of tickers, period, notes) and return 0. On `InsufficientSnapshotsError`, print the message
and return 1. If there is no price data, print a hint to `gt data download` and return 1.

## 3. Tests

Synthetic data: `random_walk_bars(1600, seed)` per ticker (≥ 250 + 120 bars, dates from
2001-01-02, turnover 50 × 1e6). Keep pool tests at N ≤ 200 and ≤ 6 tickers.

| File | Test | Asserts |
|---|---|---|
| `test_signals.py` | golden cross window | series where sma50 crosses sma200 upward at t: flag True at t, t+1, t+2, False at t+3 and at t−1 (build `ind` frames directly with chosen sma values) |
| | death cross, SMA200 up/down | same pattern |
| | RSI/BB states | chosen values → exactly the expected flags |
| | volume spike uses SMA20 up to day −1 | volume 20 × 100, then 201 → True; 200 → False (> not ≥); a spike at t doesn't raise its own baseline |
| | NaN → False | first 200 rows: no cross flags |
| | is_signal_day = any | |
| | causality | 10 seeds, random t: `signal_flags(with_indicators(b.iloc[:t+1])).iloc[t]` equals the full-series row t |
| `test_eligibility.py` | base case | 1,600 clean bars → eligible exactly for i ∈ [249, 1479] |
| | date before 2000 | series starting 1998-01-02 → rows dated before 2000-01-01 not eligible, later rows are |
| | gap > 10 days | shift dates from row 801 on by +15 days (bad pair j = 801) → rows i ∈ [681, 1050] not eligible, 680 and 1051 are; a gap of exactly 10 calendar days is fine |
| | close < 1 | scale prices to 0.5 → none eligible |
| | turnover | volume 1,000 → none eligible |
| | too short | 369 bars → none; 370 bars → only i = 249 |
| `test_pool.py` | exactly N, unique ids | N = 120, 4 tickers → 120 rows, `snapshot_id` unique, 12 hex chars |
| | every row eligible | recompute `eligible_mask` for each row's ticker and idx → True |
| | spacing | per ticker, sorted idx differ by ≥ 20 |
| | signal share | exactly `round(0.7·N)` signal rows when enough exist |
| | signal shortage | candidates with few signal days (flat-ish walk, `sigma` 0.002) → all signal candidates used, note present, N still reached |
| | insufficient | N larger than possible → `InsufficientSnapshotsError` with "benötigt" and "verfügbar" |
| | determinism | two builds with the same seed → equal frames; `write_pool` twice into two tmp dirs → identical sha256 of the parquet files |
| | different seed | different selection |
| | causality of flags | for 10 rows, flags recomputed from bars truncated at t0 equal the stored ones |
| | consistency | for 10 rows, `make_card` + `simulate` + `label` give the stored `v_*`, `exit_*`, `exit_day_*`, `label_*` |
| | report | label counts per level sum to N; `n_tickers`; period; a ticker with only 300 bars is in `tickers_without_snapshots` |
| `test_pool_store.py` | round trip | dtypes preserved; json keys sorted; no tmp files left |
| `test_cli_snapshots.py` | build | `write_store` with 4 tickers, `main(["snapshots", "build", "--n", "60", "--seed", "1"])` → 0, both files exist; `--n 100000` → 1 and "benötigt" in output; empty store → 1 |

## 4. Steps

1. `signals.py` (red → green).
2. `eligibility.py` (red → green).
3. `pool.py` selection first, then rows and `build_pool` (red → green).
4. `pool_store.py`, CLI (red → green).
5. Gate, docs (add `docs/pool.md` with schema, selection algorithm and report fields; link it from
   IMPLEMENTATION.md).
6. Manual: `time uv run gt snapshots build --n 50000 --seed 42` on the full universe, ≤ 15 min.
   Put the runtime, label distribution per level and signal share into IMPLEMENTATION.md §4. If the
   share of optimal buys is conspicuously high, name the PRD survivorship-bias trigger.

## 5. Pitfalls and performance

- A worst-case simulation (H = 120, no exit) takes ~160 µs in Decimal, so 50,000 × 9 simulations
  take ≤ ~75 s. Candidate computation is vectorized; the selection loop stops once its targets are
  reached.
- Don't compute rows for all candidates, only for the selected ones.
- `t0` in the row comes from the bars' `date` column; convert with `pd.Timestamp`. Never call
  `str(date)` for the id: use `f"{t0:%Y-%m-%d}"`.
- Sorting tickers and using a single `default_rng(seed)` is what makes the result deterministic.
  Don't iterate over sets or dicts built from unordered sources.
