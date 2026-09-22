# Snapshot pool (M4)

`gt snapshots build [--n 50000] [--seed 42]` writes `data/snapshots.parquet` (one row per
snapshot) and `data/snapshots.json` (the report). See [spec-m4-pool.md](spec-m4-pool.md) for the
full design; this doc is the schema, the selection algorithm in prose, and the manual check.

## Schema (`snapshots.parquet`)

| Column | Type | Meaning |
|---|---|---|
| `snapshot_id` | str | `sha1(f"{ticker}\|{t0:%Y-%m-%d}")[:12]`, unique per row |
| `ticker` | str | |
| `t0` | datetime64[ns] | decision day |
| `n_hist` | int64 | bars up to and including `t0` |
| `sig_<EVENT>` × 9 | bool | one flag per event in [signals.py](../src/app/signals.py) |
| `is_signal_day` | bool | any of the 9 flags |
| `v_l{L}_h{H}` | float64 | V of the K option, `L` ∈ {1, 5, 10}, `H` ∈ {10, 30, 120} |
| `exit_l{L}_h{H}` | str | `TP`/`SL`/`KO`/`TIME` |
| `exit_day_l{L}_h{H}` | int64 | day of the exit, 1..H |
| `label_l{L}` | str | first optimal option or `NEUTRAL`, for that leverage |

All V/exit/label columns use the reference balance (10,000.00 €) and default costs (D5), not the
game's actual balance or the player's chosen leverage — M6 recomputes the game's own numbers from
the same bars, this table only ranks and labels candidates.

## Eligibility and candidates ([eligibility.py](../src/app/eligibility.py))

A row is a *candidate* if it has ≥ 250 bars of history, ≥ 120 bars of future, no calendar gap of
more than 10 days within 250 bars back / 120 bars forward, close ≥ 1.0, a 20-day median turnover
≥ 1,000,000 and a defined ATR14. [signals.py](../src/app/signals.py) then flags each candidate as a
signal day or not (any of 9 technical events, each with a 3-day lookback window).

## Selection ([pool.py](../src/app/pool.py))

Deterministic for the same input and seed: candidates are flattened into one array in sorted-ticker
order, then permuted once with `numpy.random.default_rng(seed)`. Three passes over that permutation:

1. Accept signal-day candidates until `round(0.7 · N)` are reached.
2. Accept non-signal candidates until the pool would reach `N` (dynamic target: `N - <signal count
   from pass 1>`, not a fixed 30 %). **Deviation from the literal spec pseudocode**, decided during
   implementation: the spec's fixed `n_other = N - n_sig` target could leave the pool short of `N`
   whenever signal days are scarce, which contradicts D6's stated intent ("the pool has exactly
   round(0.7·N) signal days *when enough exist*" implies fewer signal days should mean *more*
   non-signal days, not an under-full pool). Making pass 2's target `N - sig_count` is the simplest
   fix consistent with D6 and leaves the common case (enough signal days) unchanged.
3. Only if the pool is still short of `N` (both categories scarce): retry unaccepted signal
   candidates. Raises `InsufficientSnapshotsError` if `N` still isn't reached.

Within a ticker, two accepted snapshots must be ≥ 20 bars apart (checked with `bisect` against a
sorted per-ticker list), so a chosen day never leaks its future bars into a neighbour's decision.

## Report (`snapshots.json`)

`n`, `seed`, `data_as_of`, `fee_rate`, `interest_rate`, `levels`, `reference_balance`,
`signal_share` (actual), `n_tickers`, `period`, `label_counts` (per level), `tickers_without_snapshots`,
`notes` (e.g. a signal shortfall). Written with `indent=2, sort_keys=True, ensure_ascii=False`;
both files are written atomically (tmp + `os.replace`).

## Manual full build (2026-09-22)

`time uv run gt snapshots build --n 50000 --seed 42` on the full 667-ticker universe:

- Runtime: 1 m 12 s (budget: ≤ 15 min).
- 667 tickers, 12 without snapshots (too little history), period 2000-01-03 – 2026-03-31.
- Signal share: 70.0 % (target reached exactly, no shortage note).
- Label distribution (buy share of the 50,000 rows): L1 44.8 %, L5 51.8 %, L10 49.1 % — roughly
  balanced between K and W labels at every leverage. The PRD's survivorship-bias trigger
  ("auffällig hoher Anteil optimaler Käufe") is **not** triggered by this build.
