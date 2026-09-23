# Implementation spec M7: features and ML model

PRD: §4 R12–R14, M7. Common rules: [spec-common.md](spec-common.md). Decisions A19, A21–A25:
[PRD.md](../PRD.md) §5.

## 1. Files

| Create / change | Content |
|---|---|
| `src/app/config.py` | `features_parquet`, `model_path`, `model_meta_path` properties |
| `src/app/features.py` | `compute_features` (R12), pure |
| `src/app/ml.py` | `build_feature_frame`, `recommend` (R13), `time_folds`, baselines, `train` (R14) |
| `src/app/model_store.py` | write/read `model.joblib` + `model.json`, write/read `features.parquet` |
| `src/app/cli.py` | `gt model train` |
| `pyproject.toml` | `scikit-learn`, `joblib` |

## 2. Design

### 2.1 `features.py` (pure)

```python
NUMERIC_FEATURES = (  # 20
    "ret_5", "ret_20", "ret_60", "ret_120", "ret_250",
    "dist_sma50", "dist_sma200", "sma_ratio", "slope_sma50", "slope_sma200",
    "rsi", "rsi_chg5",
    "bb_pctb", "bb_width", "bb_width_rank",
    "vol_rel",
    "atr_pct", "vola20",
    "dist_high252", "dist_low252",
)
FEATURE_COLUMNS = NUMERIC_FEATURES + tuple(f"sig_{e}" for e in EVENTS)   # 29, from app.signals

def compute_features(ind: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Input: bars with indicators (M2) and R11 flags, same index. One row per bar t,
    using only rows <= t. Missing history or a zero denominator -> NaN (R12)."""
```

- `ret_n = close / close.shift(n) - 1`.
- `dist_sma50/200 = close/sma - 1`; `sma_ratio = sma50/sma200 - 1`;
  `slope_sma50/200 = sma / sma.shift(20) - 1`.
- `rsi = rsi14`; `rsi_chg5 = rsi14 - rsi14.shift(5)`.
- `bb_pctb = (close - bb_lower) / (bb_upper - bb_lower)`; `bb_width = (bb_upper - bb_lower) / bb_mid`;
  `bb_width_rank = bb_width.rolling(126, min_periods=126).apply(lambda w: mean(w <= w[-1]), raw=True)`.
- `vol_rel = volume / volume.rolling(20, min_periods=20).mean().shift(1)` (same baseline as
  VOLUME_SPIKE).
- `atr_pct = atr14 / close`; `vola20 = (close/close.shift(1) - 1).rolling(20, min_periods=20).std(ddof=0)`.
- `dist_high252 = close / high.rolling(252, min_periods=252).max() - 1`;
  `dist_low252 = close / low.rolling(252, min_periods=252).min() - 1`.
- `sig_<EVENT>` = the flag column cast to float64 (0.0/1.0).
- Wrap the whole body in `np.errstate(divide="ignore", invalid="ignore")`: constant prices make
  `bb_width` 0, so `bb_pctb` is `0/0` (NaN by design, not an error).

### 2.2 `ml.py` (core, injected I/O for `build_feature_frame` and `train`)

```python
LEVELS = (1, 5, 10)              # trading.py has HORIZONS = (10, 30, 120)
QUANTILES = (0.25, 0.5, 0.75)
N_FOLDS = 4
LEVEL_OF = {1: Level.EINFACH, 5: Level.MITTEL, 10: Level.PROFI}
LoadFn = Callable[[str], pd.DataFrame]
```

**`build_feature_frame(pool_df, load) -> pd.DataFrame`**: group `pool_df` by ticker (like
`pool.build_pool`), load bars once per ticker, `with_indicators` + `signal_flags` +
`compute_features`, take the row at `i = n_hist - 1`. Columns: `snapshot_id`, `t0`,
`t_end = bars["date"].iloc[i + FUTURE]` (`FUTURE = 120`, from `app.eligibility`), then the 29
features. Reindex the result to `pool_df["snapshot_id"]` order before returning, so it aligns
positionally with a `pool_df.reset_index(drop=True)`.

**`recommend(quantiles) -> Recommendation`** (R13), pure:

```python
@dataclass(frozen=True)
class Recommendation:
    option: OptionCode
    level: Level
    p25: float
    p50: float
    p75: float

def recommend(quantiles: Mapping[tuple[int, int], tuple[float, float, float]]) -> Recommendation:
    """quantiles[(L, H)] = (p25, p50, p75), already sorted ascending."""
```

- Best pair = `min((L, H), key=lambda lh: (-quantiles[lh][0], lh[0], lh[1]))` (largest P25, ties to
  smaller L then smaller H).
- P25 of the best pair > 0 → `K_H` at `LEVEL_OF[L]`, with that pair's (P25, P50, P75).
- Else → `W_H`, `Level.EINFACH`, `H = min(HORIZONS, key=lambda h: (quantiles[(1, h)][1], h))`
  (smallest P50 at L = 1), values mirrored: `(-p75, -p50, -p25)` of `quantiles[(1, H)]`.

**`predict_quantiles(models, X) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]]`**:
per (L, H), stack the three quantile models' predictions per row and `np.sort(axis=1)` (R13's
"keine Quantil-Kreuzung").

**`time_folds(t0, t_end, n_folds=N_FOLDS) -> list[Fold]`** (R14), pure, index-position based
(`t0`/`t_end` are `pd.Series` with a plain `RangeIndex`):

```python
@dataclass(frozen=True)
class Fold:
    train_mask: np.ndarray   # bool
    test_mask: np.ndarray
```

1. `order = t0.sort_values(kind="stable").index`; the newer half is `order[len(order)//2:]`.
2. Split that half into `n_folds` contiguous, equal-size blocks with `np.array_split` (order
   preserved, so each block is a contiguous time slice of the newer half).
3. Per block: `train_mask = t_end < t0.loc[block].min()`; `test_mask` = rows in the block.

**Baselines** (R14), each `(pool_df, mask) -> float`, averaging over `pool_df.loc[mask]`:

- `baseline_always_k120`: mean of `v_l1_h120`.
- `baseline_most_frequent_label(train_df, test_df)`: most frequent `label_l1` in `train_df` that
  isn't `NEUTRAL` (empty or all-neutral → 0.0); mean of that option's V (level 1) over `test_df`.
- `baseline_random(pool_df, mask, seed)`: `default_rng(seed)` draws one of the 6 `OPTIONS`
  uniformly per row; mean of the drawn options' V at level 1.
- `option_value_l1(row, option) -> float`: `v_l1_h{horizon_of(option)}`, negated for W options.

**Per-row evaluation of a recommendation**:

- `option_values_at_level(row, level) -> dict[OptionCode, float]`: the 6 values at that level, built
  from `v_l{level}_h{10,30,120}` and their negation (mirrors `trading.option_values`, but reads
  already-stored pool values instead of simulating).
- `realized_value(row, rec) -> float`: `v_l{L}_h{H}` (L from `rec.level`) or its negation for W.
- `recommendation_points(row, rec) -> int`: `trading.points(option_values_at_level(row, L))[rec.option]`
  — no second scoring implementation.

**`train(pool_df, load, seed) -> TrainResult`** (`TrainResult` = `features`, `models`, `metadata`):

1. `pool_df = pool_df.reset_index(drop=True)`; `features = build_feature_frame(pool_df, load)`;
   `X = features[list(FEATURE_COLUMNS)]`.
2. `folds = time_folds(features["t0"], features["t_end"])`.
3. Per fold: `train_all(X[train_mask], pool_df[train_mask], seed)` (27 models: one
   `HistGradientBoostingRegressor(loss="quantile", quantile=q, random_state=seed)` per
   `(L, H, q)`, target `v_l{L}_h{H}`); `predict_quantiles` on `X[test_mask]`; `recommend` per test
   row; collect realized V, points and the three baselines over the fold's test rows.
4. Metrics: per fold and averaged over folds — `mean_v` (model) and the three baselines' `mean_v`;
   `beats_baselines` = model's overall average V > each baseline's overall average V (A25);
   `mean_points`; quantile coverage per `(L, H)`: fraction of test `v_l{L}_h{H}` ≤ the predicted P25
   and ≤ the predicted P75, averaged over folds.
5. Importance: on the last fold, train (if not already the last iteration) and use its P50 models at
   L = 1 for H ∈ {10, 30, 120}; `sklearn.inspection.permutation_importance` with
   `sklearn.metrics.make_scorer(mean_pinball_loss, alpha=0.5, greater_is_better=False)`, 5 repeats,
   `random_state=seed`; average `importances_mean` across the three horizons; report as a dict
   feature → score, sorted descending.
6. Final models: `train_all(X, pool_df, seed)` on the full data (27 models), returned in `models`.
7. `metadata`: `feature_columns` (list), `seed`, `levels`, `horizons`, `quantiles`, `n_snapshots`,
   `data_as_of` (max `t0`), `period` ([min, max] `t0`, ISO), `fold_metrics` (list of per-fold dicts),
   `mean_v_model`, `mean_v_baselines` (dict), `beats_baselines` (dict of bool per baseline),
   `mean_points`, `quantile_coverage` (dict `"l{L}_h{H}"` → `{"p25": …, "p75": …}`),
   `importance` (dict, sorted).

### 2.3 `model_store.py` (adapter)

```python
def write_features(df: pd.DataFrame, path: Path) -> None      # atomic parquet (tmp + os.replace)
def read_features(path: Path) -> pd.DataFrame
def write_model(models: Mapping[tuple[int, int, float], object],
                 metadata: Mapping[str, object], model_path: Path, meta_path: Path) -> None
                                                                # joblib.dump (tmp + os.replace) + json
def read_model(model_path: Path) -> dict[tuple[int, int, float], object]
def read_meta(meta_path: Path) -> dict[str, object]
```

- `joblib.load` only ever runs on `model_path` under `GT_DATA_DIR` (our own artifact) — never on
  user-supplied files (PRD §5 risk: pickle can execute code on load).

### 2.4 CLI

`gt model train [--seed 42]`: `store = PriceStore(cfg.prices_dir)`; if `cfg.snapshots_parquet`
doesn't exist, print a hint to `gt snapshots build` and return 1. Else `pool_store.read_pool`,
`ml.train(pool_df, store.read, seed)`, write features and model, print a German report (period,
n_snapshots, mean V model vs. baselines, `beats_baselines`, mean points, coverage, top-10
importance), return 0.

## 3. Tests

Synthetic data as in M4 (`random_walk_bars`, `write_store`). Keep training tests small: ≤ 6 tickers,
pool `N` ≤ 200, so `HistGradientBoostingRegressor` fits fast even on a fold's subset.

| File | Test | Asserts |
|---|---|---|
| `test_features.py` | fixed fixture | hand-computed values for a few rows (ret_5, dist_sma50, bb_pctb, atr_pct) match to 1e-9 |
| | causality | 10 seeds, random t: `compute_features` on `bars.iloc[:t+1]` equals the full-series row t |
| | short history | `ret_250`/`dist_high252` NaN before enough bars; `bb_width_rank` NaN before 126 valid `bb_width` values |
| | constant prices | `bb_width` = 0, `bb_pctb` NaN, no warning raised (`pytest.warns(None)` absent / `recwarn` empty) |
| | zero volume | `vol_rel` NaN, no error |
| `test_ml_recommend.py` | K wins | P25 > 0 for one pair, ties broken as specified |
| | tie-break L then H | two pairs with equal P25 → smaller L wins; equal P25 and L → smaller H |
| | all P25 ≤ 0 | W at the H with smallest P50(L=1); mirrored quantiles |
| | quantile sort in `predict_quantiles` | deliberately crossed fake model predictions come out sorted |
| `test_ml_folds.py` | 4 folds, embargo | synthetic `t0`/`t_end` (regular spacing) → folds cover exactly the newer half, contiguous, no overlap; every train row's `t_end` < the fold's test block's min `t0` |
| `test_ml_baselines.py` | fixed small pool_df | `baseline_always_k120`, `baseline_most_frequent_label`, `baseline_random` (fixed seed) match hand-computed values |
| | `recommendation_points` | matches `trading.points` on the same values dict |
| `test_ml_features_frame.py` | `build_feature_frame` | on a small `write_store` pool: row count, column set, values match direct `compute_features` calls at the snapshot's index; order matches `pool_df` |
| `test_ml_train.py` | end-to-end on a small pool (N=120, 5 tickers) | `models` has 27 entries; `metadata` has the documented keys; `quantile_coverage` values in [0, 1]; determinism (same seed twice → identical `metadata["mean_v_model"]` and `metadata["importance"]`) |
| `test_model_store.py` | round trip | `read_model`/`read_meta`/`read_features` reproduce what was written; no tmp files left |
| `test_cli_model.py` | `gt model train` | on a built pool: exit 0, both files exist, report printed; no pool → hint + exit 1 |

## 4. Steps

1. `features.py` (red → green).
2. `ml.py`: `recommend`, `predict_quantiles`, `time_folds`, baselines, per-row evaluation (all pure,
   red → green).
3. `ml.py`: `build_feature_frame` (red → green).
4. `ml.py`: `train` end-to-end (red → green).
5. `model_store.py`, `config.py` properties, CLI (red → green).
6. Gate, docs (`docs/architecture.md` data flow, IMPLEMENTATION.md module map and phase row).
7. Manual: `time uv run gt model train` on the full pool, ≤ 15 min; report `beats_baselines`,
   coverage and top-10 importance in IMPLEMENTATION.md §4.

## 5. Pitfalls

- `HistGradientBoostingRegressor(loss="quantile", quantile=q)` needs `random_state` for
  determinism; default hyperparameters otherwise (no early stopping tuning — out of scope for M7).
- Quantile crossing is real with small folds; always sort predictions per row before using them.
- `t_end` must come from the ticker's own bar dates (`bars["date"].iloc[i + 120]`), not `t0 +
  pd.Timedelta(days=120)` (calendar days ≠ trading days).
- `build_feature_frame` must load each ticker once, like `pool.build_pool` — don't reload per
  snapshot row.
- `joblib.dump`/`load` round-trips a `dict[tuple[int, int, float], HistGradientBoostingRegressor]`
  without issue; don't try to serialize models as JSON.
