# Implementation spec M7.1: model improvement

PRD: §4 R12–R14 (v0.6), M7.1; §5 A19, A22, A25, A26. This spec lists only the changes to
[spec-m7-model.md](spec-m7-model.md); everything not named here stays as in M7.
Evidence for the choices: PRD M7.1 "Anlass" and IMPLEMENTATION.md §4.

## 1. Files

| Create / change | Kind | Change |
|---|---|---|
| `src/app/market.py` | core, injected I/O | new: `market_frame` (R12 market part) |
| `src/app/features.py` | core | `STOCK_FEATURES` (the old 29), `FEATURE_COLUMNS` (37), `with_market` |
| `src/app/ml.py` | core | L ∈ {1, 5}; growth rule (R13); growth metrics and baselines (R14); hyperparameters |
| `src/app/model_store.py` | adapter | `write_market` / `read_market` |
| `src/app/config.py` | core | `market_parquet` property (`data_dir / "market.parquet"`) |
| `src/app/cli.py` | entry | `gt model train` builds and writes the market table; new report |

## 2. Design

### 2.1 `market.py`

```python
MIN_TICKERS = 30
GLITCH = 0.5  # |daily return| > 50 % counts as a data error
MARKET_COLUMNS = (
    "mkt_ret_20",
    "mkt_ret_60",
    "mkt_ret_250",
    "mkt_dist_sma200",
    "mkt_vola20",
    "mkt_breadth200",
)
LoadFn = Callable[[str], pd.DataFrame]


def market_frame(
    tickers: Sequence[str], load: LoadFn, min_tickers: int = MIN_TICKERS
) -> pd.DataFrame:
    """Index: `date` (datetime64[ns], ascending) = union of all tickers' dates.
    Columns: MARKET_COLUMNS. Rows with < min_tickers returns are all NaN."""
```

Split into helpers to respect the 50-line/complexity-10 limits:

1. `_ticker_series(bars) -> tuple[pd.Series, pd.Series]` (index `date`): the ticker's own daily
   return `close.pct_change()` with `abs > GLITCH` set to NaN; above-SMA200 as float
   (`(close > sma200).astype("float64").where(sma200.notna())`).
2. Wide frames `R`, `A`: `pd.concat(series, axis=1, sort=True)` over `sorted(tickers)`.
3. `n = R.notna().sum(axis=1)`; `m = R.mean(axis=1).where(n >= min_tickers)`;
   `index = (1 + m.fillna(0.0)).cumprod()`.
4. `mkt_ret_k = index / index.shift(k) - 1`; `mkt_dist_sma200 = index / index.rolling(200,
   min_periods=200).mean() - 1`; `mkt_vola20 = m.rolling(20, min_periods=20).std(ddof=0)`;
   `mkt_breadth200 = A.mean(axis=1).where(A.notna().sum(axis=1) >= min_tickers)`.
5. Finally `.where(n >= min_tickers)` on the whole frame.

Memory for the full store (≈ 670 tickers × ≈ 7,000 dates, two float frames) is ≈ 75 MB, fine for
a CLI run. Returns are per ticker over its own consecutive bars, so a ticker's holiday doesn't
create a fake zero return.

### 2.2 `features.py`

```python
STOCK_FEATURES = (...)                # exactly the old FEATURE_COLUMNS (29), same order
RELATIVE_FEATURES = ("rs_60", "rs_250")
FEATURE_COLUMNS = STOCK_FEATURES + MARKET_COLUMNS + RELATIVE_FEATURES   # 37

def compute_features(ind, flags) -> pd.DataFrame      # unchanged, returns STOCK_FEATURES

def with_market(stock: pd.DataFrame, dates: pd.Series, market: pd.DataFrame) -> pd.DataFrame:
    """`stock` rows align positionally with `dates`. Joins the latest market row <= each date
    (pd.merge_asof, direction="backward") and adds rs_60/rs_250. Returns FEATURE_COLUMNS."""
```

`merge_asof` needs sorted keys: sort by date with a positional helper column, merge, restore the
original order. For a pool snapshot the date exists in the market index (its ticker traded that
day), so backward matches exactly; M8 reuses the same function for "latest row ≤ Tag 0".

### 2.3 `ml.py`

```python
LEVELS = (1, 5)                                  # A19: never Profi
LEVEL_OF = {1: Level.EINFACH, 5: Level.MITTEL}
HYPERPARAMS = {"learning_rate": 0.05, "min_samples_leaf": 200,
               "max_leaf_nodes": 15, "l2_regularization": 1.0}
DEFAULT_MAX_ITER = 200
LOG_FLOOR = -0.99
BASELINES = {"never": None, "k120_l1": (1, 120), "k120_l5": (5, 120)}

def growth_score(q: tuple[float, float, float]) -> float   # mean(log1p(max(x, LOG_FLOOR)))
def growth(booked: np.ndarray) -> float                    # mean(log1p(booked)); empty -> 0.0
def booked_value(row: pd.Series, rec: Recommendation) -> float   # K: v_l{L}_h{H}; W: 0.0
```

- `Recommendation` gains `growth: float` (G of the chosen pair; for W, G of K_H at L = 1).
- `recommend`: best pair = `min(pairs, key=lambda lh: (-G[lh], lh[0], lh[1]))`; `G > 0` → K,
  else W exactly as before.
- `build_feature_frame(pool_df, load, market)`: stock features as in M7, then `with_market` with
  `dates = t0`. Output columns: `snapshot_id`, `t0`, `t_end`, then `FEATURE_COLUMNS`.
- `_make_regressor(q, seed, max_iter)`: `HistGradientBoostingRegressor(loss="quantile",
  quantile=q, random_state=seed, max_iter=max_iter, **HYPERPARAMS)`. 18 models.
- Remove `baseline_always_k120`, `baseline_most_frequent_label`, `baseline_random` and
  `option_value_l1` (only M7's evaluation used them); keep `realized_value` and
  `recommendation_points` for the secondary game view.
- Per fold (`_evaluate_fold`): booked values of the model and of each baseline on the fold's test
  rows (`never` → zeros; `(L, H)` → `v_l{L}_h{H}`), the game V list, points, coverage, trade share.
- Aggregate (`_aggregate_folds`), all weighted by rows where a mean is involved:

| Key | Content |
|---|---|
| `growth_model` | `growth` over all test rows |
| `growth_baselines` | dict name → `growth` over all test rows |
| `beats_baselines` | dict name → `growth_model > growth_baselines[name]` (A25) |
| `fold_growth` | list per fold: `{"model": …, "<baseline>": …}` |
| `worst_fold_growth` | dict `"model"` and each baseline → min over folds |
| `all_folds_positive` | model's fold growth > 0 in every fold |
| `traded_share` | share of test rows with a K recommendation |
| `booked_p5` | 5 % quantile of the model's booked values |
| `mean_v_model`, `mean_points` | game view (secondary) |
| `quantile_coverage` | as in M7, for the 6 pairs |

- `train(pool_df, load, market, seed, max_iter=DEFAULT_MAX_ITER)`; metadata as in M7 (with
  `feature_columns` now 37 names and `levels` [1, 5]) plus the keys above; the M7 keys
  `mean_v_baselines` and the old `beats_baselines` meaning are gone.

### 2.4 `model_store.py`, `config.py`, CLI

- `write_market(df, path)`: `df.reset_index()` (column `date`) to parquet, atomic; `read_market(path)`
  returns it indexed by `date` again.
- `gt model train`: `tickers = store.tickers()`; `mkt = market.market_frame(tickers, store.read)`;
  `model_store.write_market(mkt, cfg.market_parquet)`; `ml.train(pool_df, store.read, mkt, seed)`.
- German report: growth of model and baselines (in %, 3 decimals), "geschlagen: ja/nein" per
  baseline, growth per fold, worst fold, "alle Folds positiv", traded share, 5 % quantile, game V and
  points (marked "Spiel-Sicht"), coverage, top-10 importance.

## 3. Tests

| File | Test | Asserts |
|---|---|---|
| `test_market.py` (new) | hand values | 3 synthetic tickers, `min_tickers=2`: `m_t`, `mkt_ret_20` and breadth at chosen dates equal hand-computed values |
| | threshold | a date where only 1 ticker has a return → whole row NaN |
| | glitch | a +80 % jump is ignored in `m_t` |
| | causality | truncating every ticker after date t leaves row t unchanged |
| | own-calendar returns | a ticker missing one date doesn't get a 0 % return for it |
| `test_features.py` | counts | `STOCK_FEATURES` 29, `FEATURE_COLUMNS` 37, no duplicates; old tests use `STOCK_FEATURES` |
| | `with_market` | exact-date match, backward match for a date between market rows, `rs_60 = ret_60 − mkt_ret_60`, order of rows preserved |
| `test_ml_recommend.py` | growth rule | G formula incl. floor at −0.99; K when G > 0; ties (smaller L, then H); G ≤ 0 → W at argmin P50; only L ∈ {1, 5} keys needed |
| `test_ml_metrics.py` (replaces `test_ml_baselines.py`) | growth | `growth` of known values; empty → 0 |
| | booked vs game | `booked_value` W → 0, K → stored v; `realized_value` unchanged |
| | aggregate | synthetic fold results → `beats_baselines`, `worst_fold_growth`, `all_folds_positive` as hand-computed |
| `test_ml_features_frame.py` | columns | 37 features + ids; market columns equal the market row of each t0 |
| `test_ml_train.py` | models, keys | 18 models; new metadata keys; determinism |
| `test_model_store.py` | market round trip | index and values survive |
| `test_cli_model.py` | train | `market.parquet` written; report contains "Wachstum" |

## 4. Steps

1. `market.py` (red → green). 2. `features.py` (red → green). 3. `ml.py` rule and metrics
(red → green). 4. `build_feature_frame`/`train`, store, CLI (red → green). 5. Gate. 6. Manual:
`time uv run gt model train` on the full pool; compare with the experiment (growth ≈ +0.31 %/round,
all folds positive, traded ≈ 70 %, 5 % quantile ≈ −6 %). Report deviations; don't tune toward the
target. 7. Docs.

## 5. Pitfalls

- The experiment used exactly these hyperparameters, features and folds; any deviation (another
  glitch threshold, other min tickers, calendar returns) changes the numbers — keep them as specified.
- `min_samples_leaf=200` makes test-size folds fit root-only trees (constant predictions). That's
  fine for structural tests; don't assert model quality on synthetic pools.
- `market_frame` must not import `features` (features imports market's column names).
- Thread oversubscription: never run several training processes in parallel on this machine;
  HistGradientBoosting already uses all cores (observed: 3 parallel runs took > 27 min instead of
  3 × 20 s).
