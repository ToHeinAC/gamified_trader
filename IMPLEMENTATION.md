# IMPLEMENTATION

Current state of the code, and the only place for phase status. What and why: [PRD.md](PRD.md).
Rules: [AGENTS.md](AGENTS.md). Design: [docs/architecture.md](docs/architecture.md).

## 1. Run and verify

| Task | Command |
|---|---|
| Install (once per clone) | `uv sync && uv run pre-commit install` |
| Tests (fast loop) | `uv run pytest` or `uv run pytest tests/test_chart.py` |
| Kursdaten laden/aktualisieren | `uv run gt data download` / `uv run gt data update` |
| App starten | `uv run gt app` (port `GT_PORT`, default 8537) |
| Full gate | `uv run pre-commit run --all-files` |

## 2. Phase status

One row per PRD milestone. Status: `planned`, `in progress`, `done`. Implementation specs for
Release 1: start with [docs/spec-common.md](docs/spec-common.md), then the milestone's spec.

| Phase | Milestone | Status | Verified by | Spec |
|---|---|---|---|---|
| 0 | Blueprint skeleton (no PRD milestone) | done | full gate green | — |
| 1 | M1: Kursdaten und Universum | done | acceptance tests M1, full gate green | [M1](docs/spec-m1-data.md) |
| 2 | M2: Indikatoren, Chart und App-Grundgerüst | done | acceptance tests M2, full gate green | [M2](docs/spec-m2-chart-app.md) |
| 3 | M3: Handelsvorschläge, Simulation und Bewertung | done | acceptance tests M3, full gate green | [M3](docs/spec-m3-trading.md) |
| 4 | M4: Snapshot-Pool (50.000) | done | acceptance tests M4, full gate green | [M4](docs/spec-m4-pool.md) |
| 5 | M5: Persistenz und Setup-Modus | planned | acceptance tests M5 | [M5](docs/spec-m5-setup.md) |
| 6 | M6: Spielmodus | planned | acceptance tests M6 | [M6](docs/spec-m6-game.md) |
| 7 | M7: Features und ML-Modell (preliminary) | planned | after PRD iteration | — |
| 8 | M8: Entdeckungsmodus (preliminary) | planned | after PRD iteration | — |
| 9 | M9: Lernmodus (preliminary) | planned | after PRD iteration | — |

## 3. Module map

| Module | Responsibility |
|---|---|
| `src/app/config.py` | `Config` dataclass from environment variables. |
| `src/app/cleaning.py` | `clean_prices`: OHLCV validation and correction rules. |
| `src/app/yahoo.py` | The only module importing `yfinance`: `fetch_batch`, `split_download`, `normalize_frame`. |
| `src/app/price_store.py` | `PriceStore`: atomic parquet read/write for `data/prices/<TICKER>.parquet`. |
| `src/app/data_sync.py` | `download`/`update` loops with retry, batching and `SyncReport` (D13 reload logic). |
| `src/app/universe.py` | Reads the ticker universe from `resources/universe.csv`. |
| `src/app/resources/universe.csv` | 668-row ticker universe; built once, see [docs/data.md](docs/data.md). |
| `src/app/indicators.py` | `with_indicators`: SMA, Bollinger, Wilder RSI/ATR (R1). |
| `src/app/theme.py` | `LIGHT`/`DARK` design tokens, `page_css()`. |
| `src/app/chart.py` | `decision_window` (leak-proof, drops `date`), `build_figure`, presets (R2). |
| `src/app/ui/root.py` | App shell: header, theme resolution, routing (`root()`, `run_app()`). |
| `src/app/ui/chart_panel.py` | Preset buttons + `ui.plotly` panel, reused unchanged in M6. |
| `src/app/ui/play.py` | Page "Spielen": picks a random ticker/day and shows its chart. |
| `src/app/trading.py` | `make_card(s)`, `simulate(_all)`, `option_values`/`points`/`label`/`book`: R3–R9, pure Decimal math. |
| `src/app/signals.py` | `signal_flags`: 9 technical event flags per bar (R11). |
| `src/app/eligibility.py` | `eligible_mask`: R10 candidate mask per bar. |
| `src/app/pool.py` | `ticker_candidates`, `select`, `build_pool`: deterministic snapshot selection and rows. See [docs/pool.md](docs/pool.md). |
| `src/app/pool_store.py` | `write_pool`/`read_pool`/`read_meta`: `snapshots.parquet` + `snapshots.json`. |
| `src/app/cli.py` | `gt` entry point: `data download`, `data update`, `app`, `snapshots build`. |
| `tests/helpers.py` | Synthetic OHLCV factories (`make_bars`, `random_walk_bars`, `write_store`). |
| `tests/conftest.py` | Shared fixtures; blocks network access in all tests. |
| `tests/test_code_rules.py` | Enforces functions ≤ 50 lines in `src/`, `tests/`, `.claude/hooks/`. |
| `tests/test_docs.py` | Enforces doc size limits and resolvable local links. |
| `.claude/hooks/format_on_edit.py` | PostToolUse hook: ruff-formats each `.py` file Claude edits. |
| `.claude/hooks/stop_gate.py` | Stop hook: runs the gate if `.py` files changed; blocks the stop on failure. |

## 4. Open issues

- [PRD.md](PRD.md) v0.2: grill-me settled A1–A18 (Release 1 is ready to implement). A19 and A20
  stay open and must be settled in a separate PRD iteration before M7 starts.
- M1 manual check (2026-09-22): full `gt data download` succeeded for 666/668 tickers (99.7 %,
  above the 95 % threshold). 1 failure was a universe-CSV suffix bug (fixed); the other is a
  legitimately delisted ticker. Details: [docs/data.md](docs/data.md#manual-full-download-2026-09-22).
- M2 manual check (2026-09-22): `uv run gt app` serves the page on the real universe data; automated
  `test_ui_shell.py` covers presets, theme toggle/persistence and shutdown. The visual comparison
  against `docs/ui/references/` is a manual step for the user (spec §5).
- M2 pyright: two NiceGUI 3.17.1 stub gaps needed a scoped `pyright: ignore[reportUnknownMemberType]`
  each (`ui/root.py`'s `ui.run`, `ui/chart_panel.py`'s `update_figure`) — both verified in isolation
  to be gaps in nicegui's own stubs (bare `Callable`/unstubbed `Figure` reference), not our code.
- M3 (2026-09-22): `trading.py` implemented exactly per spec, no deviations. No manual checks for
  this milestone (pure module, no UI/CLI wiring yet — M4/M6 call it).
- M4 manual check (2026-09-22): `gt snapshots build --n 50000 --seed 42` on the full universe took
  1 m 12 s (budget ≤ 15 min); 667 tickers, 12 without snapshots, signal share 70.0 % exactly, buy
  share 45–52 % across leverages (PRD survivorship-bias trigger not hit). Details:
  [docs/pool.md](docs/pool.md#manual-full-build-2026-09-22).
- M4 pyright: numpy's own overloads for `cumsum`, `where`, `flatnonzero`, `concatenate` and
  `permutation` are ambiguous under strict mode (verified in isolation, outside project settings,
  same class of stub gap as M2's NiceGUI/plotly issues) — 7 scoped
  `pyright: ignore[reportUnknownMemberType]` across `eligibility.py` and `pool.py`, each commented.
- M4 `pool.py` `select`: the spec's literal pseudocode gives pass 2 (non-signal fill) a fixed target
  `N - n_sig`, which can leave the pool short of `N` when signal days are scarce. Implemented pass
  2's target as `N - <actual signal count>` instead (dynamic), matching D6's stated intent that a
  signal shortage should be made up by *more* non-signal days, not a smaller pool. Documented in
  [docs/pool.md](docs/pool.md#selection-poolpy).
