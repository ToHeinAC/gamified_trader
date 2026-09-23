# IMPLEMENTATION

Current state of the code, and the only place for phase status. What and why: [PRD.md](PRD.md).
Rules: [AGENTS.md](AGENTS.md). Design: [docs/architecture.md](docs/architecture.md).

## 1. Run and verify

| Task | Command |
|---|---|
| Install (once per clone) | `uv sync && uv run pre-commit install` |
| Tests (fast loop) | `uv run pytest` or `uv run pytest tests/test_chart.py` |
| Kursdaten laden/aktualisieren | `uv run gt data download` / `uv run gt data update` |
| Snapshot-Pool bauen | `uv run gt snapshots build --n 50000 --seed 42` |
| ML-Modell trainieren | `uv run gt model train --seed 42` (writes market table, features, model) |
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
| 5 | M5: Persistenz und Setup-Modus | done | acceptance tests M5, full gate green | [M5](docs/spec-m5-setup.md) |
| 6 | M6: Spielmodus | done | acceptance tests M6, full gate green | [M6](docs/spec-m6-game.md) |
| 6b | M6.1: Desktop-Layout | done | acceptance tests M6.1, full gate green | PRD §4 M6.1 |
| 7 | M7: Features und ML-Modell | done | acceptance tests M7, full gate green | [M7](docs/spec-m7-model.md) |
| 7b | M7.1: Modellverbesserung | done | acceptance tests M7.1, full gate green | [M7.1](docs/spec-m7-1-improve.md) |
| 8 | M8: Entdeckungsmodus | done | acceptance tests M8, full gate green | [M8](docs/spec-m8-discover.md) |
| 9 | M9: Lernmodus | planned | after M7 | — |

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
| `src/app/chart.py` | `decision_window`/`resolution_window` (leak-proof, drop `date`), `discover_window`/`build_discover_figure` (real dates, M8), `build_figure`, `build_resolution_figure`, `add_preview`, presets (R2). |
| `src/app/ui/root.py` | App shell: header, theme resolution, routing (`root()`, `run_app()`); links Spielen/Entdecken/Setup. |
| `src/app/ui/chart_panel.py` | `ui.plotly` panel from a figure factory; optional preset buttons. |
| `src/app/ui/play.py` | Page "Spielen": `PlayPage`/`DecisionView`/`ResolutionView`, the full round loop. |
| `src/app/trading.py` | `make_card(s)`, `simulate(_all)`, `option_values`/`points`/`label`/`book`: R3–R9, pure Decimal math. |
| `src/app/signals.py` | `signal_flags`: 9 technical event flags per bar (R11). |
| `src/app/eligibility.py` | `eligible_mask`: R10 candidate mask per bar. |
| `src/app/pool.py` | `ticker_candidates`, `select`, `build_pool`: deterministic snapshot selection and rows. See [docs/pool.md](docs/pool.md). |
| `src/app/pool_store.py` | `write_pool`/`read_pool`/`read_meta`: `snapshots.parquet` + `snapshots.json`. |
| `src/app/settings_rules.py` | Pure validation for the Setup form (names, capital, leverage, rates). |
| `src/app/fmt.py` | German number/money/date formatting for the UI. |
| `src/app/db.py` | `Database`: SQLite users/settings/resets/active-user (`data/app.db`). |
| `src/app/ui/context.py` | `PageContext`: per-client `Config`/`Database`/theme/user name shared by pages. |
| `src/app/ui/setup.py` | Page "Setup": create/select users, edit settings, reset balance. |
| `src/app/game.py` | Pure: `draw_snapshot`, `Setting`, `card_lines`, `resolve`, `outcome`, `round_number`, `badge_tier` (R1–R9, D7, D9). |
| `src/app/game_service.py` | `GameService`: wires DB, pool and prices for `start_round`/`confirm`/`resolution`. |
| `src/app/cli.py` | `gt` entry point: `data download`/`update` (also refresh `market.parquet`), `app`, `snapshots build`, `model train`. |
| `tests/helpers.py` | Synthetic OHLCV factories (`make_bars`, `random_walk_bars`, `write_store`). |
| `tests/conftest.py` | Shared fixtures; blocks network access in all tests. |
| `tests/test_code_rules.py` | Enforces functions ≤ 50 lines in `src/`, `tests/`, `.claude/hooks/`. |
| `tests/test_docs.py` | Enforces doc size limits and resolvable local links. |
| `.claude/hooks/format_on_edit.py` | PostToolUse hook: ruff-formats each `.py` file Claude edits. |
| `.claude/hooks/stop_gate.py` | Stop hook: runs the gate if `.py` files changed; blocks the stop on failure. |
| `src/app/market.py` | `market_frame`/`market_return`: equal-weight market-regime features per date (R12, A26). |
| `src/app/features.py` | `compute_features` (29 stock features), `with_market` (+6 market, +2 relative = 37, R12). |
| `src/app/ml.py` | `recommend` (growth rule, R13), `time_folds`, growth metrics/baselines, `build_feature_frame`, `train` (R14). |
| `src/app/model_store.py` | `data/features.parquet`, `data/market.parquet`, `data/models/model.joblib`/`model.json` read/write. |
| `src/app/discover.py` | Pure M8 rules: ticker check, cache freshness, `analyze` (R13 on the last completed bar), `recommendation_card`. |
| `src/app/discover_store.py` | `DiscoverStore`: `data/discover/<TICKER>.parquet` + `meta.json` (fetch date, quote type). |
| `src/app/discover_service.py` | `DiscoverService`: Yahoo fetch-or-cache, mtime-cached model/market/pool-feature loaders. |
| `src/app/ui/discover.py` | Page "Entdecken": ticker input, chart, recommendation card, quantile table, top features, hints. |

## 4. Open issues

- [PRD.md](PRD.md) v0.3: grill-me settled A1–A18 (Release 1 is ready to implement). A19 and A20
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
- M5 (2026-09-22): implemented exactly per spec, no deviations. Manual check: `uv run gt app`
  served "/" (shows "Noch kein Nutzer angelegt." with no user) and "/setup" (shows "Neuer Nutzer")
  correctly; stopped via its own shutdown (SIGTERM to its own PID), not a port-kill. Automated
  `test_ui_setup.py` covers user creation, settings validation/save, and the reset-confirmation
  dialog. Two elements needed distinct `.mark(...)` markers ("cancel-reset"/"confirm-reset") beyond
  what the spec's UI table names, because NiceGUI's `find()` text search is substring-based and
  "Guthaben zurücksetzen" and "Zurücksetzen" would otherwise collide.
- M6 (2026-09-22): implemented exactly per the round-lifecycle rules (D7, D9); one implementer
  decision on `chart_panel`'s signature (below). Manual checks on the real universe + M4's pool:
  60 rounds (20 per level) via `GameService` directly, all confirmed without error, timings well
  inside budget (`start_round` ≤ 0.12 s warm, `resolution` ≤ 0.014 s, vs. the 2 s/1 s targets);
  `uv run gt app` served the decision view (SL/TP/CRV lines, buy/wait cards) on real data, stopped
  via its own shutdown. Phone-width layout and light/dark screenshots need a real browser and are
  a pending manual step for the user (no browser available in this environment).
- M6 `chart_panel` signature: the spec's `chart_panel(ctx, make_figure, presets)` omits how preset
  buttons recompute their range without the source `DataFrame`. Kept an explicit `window` parameter
  (`chart_panel(ctx, window, make_figure, presets)`) since `apply_preset` needs it; `make_figure`
  still carries the caller's theme-dependent figure logic (including the decision view's preview
  overlay), so the spec's "presets rebuild with apply_preset" / "decision view passes a closure
  that also applies the current preview" both hold.
- M6.1 (2026-09-22): implemented per PRD §4 M6.1 — CSS-only (Tailwind `lg:` breakpoint), no new
  logic. Details: [docs/architecture.md](docs/architecture.md#m61-desktop-layout). Manual check via
  headless Chromium (Playwright, since no interactive browser is available in this environment):
  `gt app` on real data, real user; 1440 px shows the two-pane Spielen layout and the paired Setup
  cards; 1023 px falls back to the exact M6 stacked layout; 390 px unchanged. One real bug found and
  fixed this way (not catchable by the class-only `User`-fixture tests): Quasar's `.flex` utility
  collided with Tailwind's, wrapping the two panes despite a correct `flex-direction: row` — see
  architecture doc for the fix and the general gotcha.
- M6.1 follow-up (2026-09-22): green selection frame for the picked option card, and a CSS-grid
  right panel for `ResolutionView` (Guthaben/Punkte/Runde tiles, result table, "Nächste Runde",
  Statistics) mirroring the decision view's chart-left/options-right split at ≥1024 px. Details:
  [docs/architecture.md](docs/architecture.md#selected-card-frame-and-the-resolution-grid-2026-09-22).
  Manual check via headless Chromium: green border/glow renders, and the resolution grid areas sit
  in two real columns at 1440 px with no change to the 390 px stacked order.
- M7 (2026-09-23): PRD v0.4 settled A19–A25 (risk-adjusted recommendation via pessimistic quantiles,
  learning content as Markdown files) and added R12–R14; implemented per
  [spec-m7-model.md](docs/spec-m7-model.md), no deviations from that spec. `HistGradientBoostingRegressor`
  needs `max_iter` lowered in tests to stay inside the 60 s suite budget (spec §5); production code
  keeps the sklearn default (100) via a parameter, not a global change.
- M7 pyright (D14 in [spec-common.md](docs/spec-common.md)): scikit-learn and joblib ship no type
  stubs, the same root cause as M1's yahoo.py and M2's chart.py. Extended the header-pragma
  convention to `ml.py` (two extra flags: `reportUnknownVariableType`, `reportUnknownArgumentType`,
  because sklearn's own partial type hints — not just missing stubs — leak through) and to
  `model_store.py` (joblib only).
- M7 manual check (2026-09-23): `uv run gt model train --seed 42` on the full pool (50,000 snapshots,
  2000-01-03 to 2026-03-31) took 55 s (budget ≤ 15 min). Ø V model 0.0048 vs. baselines: beats
  "immer K120 Einfach" (0.0005) and "Zufall" (−0.0000), does **not** beat "häufigstes Label" (0.0052)
  — `beats_baselines` is therefore mixed, not unanimous. Quantile coverage is well calibrated (P25
  ≈ 0.23–0.28, P75 ≈ 0.74–0.77 against targets 0.25/0.75). Permutation importance is small and flat
  across features (top: `dist_low252`, `rsi`, `dist_high252`, all ≤ 0.00004 pinball-loss reduction),
  i.e. the model captures little beyond what the simple label baseline already gets from market
  drift. M8's PRD-mandated hint ("Das Modell schlägt die einfachen Vergleichsstrategien nicht") must
  therefore show for at least one baseline; Gesamtprodukt DoD's "Modell schlägt Baselines, oder die
  UI weist klar darauf hin" is met via that hint, not via unanimously beating all three baselines.
- M7.1 (2026-09-23): PRD v0.6 after the M7 findings: the P25 rule never bought (K share 0 %) and
  game-V rewarded waiting through the avoided 2 % fee, so "häufigstes Label" (W10) won by
  construction. Now: growth rule G (R13), growth metric against never/K120 L1/K120 L5 (R14, A25),
  8 market-regime features (A26), leverage capped at Mittel (A19), regularized hyperparameters.
  Chosen from scratchpad experiments on the full pool (3 hyperparameter sets × with/without market
  features × 3 or 5 quantiles × 10 decision rules); 5 quantiles and stronger/weaker regularization
  didn't help. Implemented per [spec-m7-1-improve.md](docs/spec-m7-1-improve.md); one addition:
  sklearn 1.9.1 raises on an all-NaN feature column (market features with < 30 tickers, e.g. small
  test stores), so `train_all` sets such columns to 0 before fitting (verified in isolation).
- M7.1 manual check (2026-09-23): `gt model train --seed 42` on the full pool took 74 s. Growth
  +0.307 % per round (folds +0.274/+0.432/+0.311/+0.209 %, all positive), 70 % of rounds traded,
  5 % quantile −6.10 % of B — identical to the experiment. Baselines: never 0, K120 Einfach
  +0.036 % (worst fold −0.074 %), K120 Mittel +0.378 % (worst fold −0.194 %, 2020–23). So the model
  beats two of three baselines; it trails "always K120 Mittel" on average but is the only strategy
  positive in every period. Game view (secondary): Ø V +0.0059 (M7: +0.0048), Ø Punkte 43.3.
  Coverage P25 0.23–0.28, P75 0.71–0.73. Top importance: `mkt_breadth200`, `mkt_ret_60`,
  `mkt_vola20`, then stock features. Caveat: evidence rests on 4 folds, and the hyperparameters and
  features were picked on those same folds — treat the stability result as indicative, not proven.
- M6 gamified result badge (2026-09-23): UI polish, no PRD change. `game.badge_tier` classifies the
  chosen option's result (`optimal`/`gut`/`neutral`/`schlecht`) from `Resolution`; `ResolutionView`
  shows it as a `.gt-badge-*` chip with a CSS pop-in (and a glow pulse for `optimal`), and the tiles
  pane gets the same pop-in on round resolution. No count-up animation: the CSS-only pop/glow
  approach was chosen over JS-driven number counting since NiceGUI's test simulation cannot execute
  client JS, so a JS count-up would be unverifiable by the automated suite. Details:
  [docs/architecture.md](docs/architecture.md#gamified-result-badge-2026-09-23). Automated
  `test_ui_play.py::test_resolution_shows_result_badge` covers the badge; the CSS animation itself
  needs a manual browser check (no browser available in this environment), same class of gap as
  M6.1's screenshots.
- M8 (2026-09-23): implemented per [spec-m8-discover.md](docs/spec-m8-discover.md), no deviations
  from the spec's own decisions. Page "Entdecken" caches Yahoo history under `data/discover/`
  (never touching `data/prices/`, verified by a test that runs `gt snapshots build` afterward and
  checks the new ticker is absent), falls back to cached data with a "veraltet" hint on a failed
  fetch, and shows the R13 growth recommendation with a position-size card for the active user.
  `gt data download`/`update` now also rewrite `data/market.parquet` so Entdecken stays current
  without a retrain. One fix during implementation: `ui/discover.py` initially imported
  `discover_service.load_bundle` by name, which would have made the `discover_service.load_bundle`
  monkeypatch target from the spec's test plan invisible to the UI (the same "call module.func(),
  don't import func by name" rule as spec-common.md's CLI recipe) — changed to a module-qualified
  call before writing the UI tests.
- M8 pyright/ruff: 0 errors on the first implementation pass for every new module; no new
  `# pyright: ignore` needed (`discover.py`/`discover_service.py` avoid sklearn entirely, per the
  spec's pitfall list). `ruff` flagged literal en dashes in the German hint texts
  (`RUF001`, ambiguous-unicode); switched to `–` escapes, matching `settings_rules.py`'s
  existing convention for the same character.
- M8 manual check (2026-09-23): automated coverage is full (`test_ui_discover.py` covers the nav
  link, invalid input, an unknown ticker, the OK path with chart and recommendation, every hint,
  and the Enter key). Network access turned out to be available in this environment, so the PRD's
  network-dependent step ran for real via `DiscoverService.analyze` directly (no browser available,
  same fallback as M6's "60 rounds via `GameService` directly"): `uv run gt data update` refreshed
  all 667 tickers and printed "Markttabelle bis 23.09.2026"; then AAPL (cold 1.08 s / warm 0.09 s),
  SAP.DE (0.39 s / 0.07 s), CELH — a stock outside `universe.csv` (1.14 s / 0.06 s, `quote_type`
  correctly resolved to `EQUITY` via a real `yf.Ticker(...).info` call), SPY (1.51 s / 0.01 s,
  correctly `NOT_EQUITY`, no recommendation), and `../x` (rejected by `normalize_ticker` before any
  network call). All cold/warm timings are inside the ≤ 5 s/≤ 1 s budget. `data/discover/` held
  exactly the 4 fetched tickers plus `meta.json` afterward; `data/prices/` stayed at 667 tickers,
  confirming A21. The two-pane layout itself (CSS/visual) still needs a real or headless browser,
  which this environment doesn't have (same class of gap as M6.1's screenshots); the automated
  `test_ui_discover.py::test_ok_path_shows_recommendation_and_chart` covers its structure.
