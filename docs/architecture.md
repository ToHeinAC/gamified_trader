# Architecture

## Code layers

| Layer | Where | Rule |
|---|---|---|
| Core logic | `src/app/*.py` | Pure functions, fully typed, no I/O. Unit-tested directly. |
| Adapters | `src/app/<adapter>.py` (add when needed) | The only place for network, file, or database I/O. |
| Entry points | CLI / app module (add when needed) | Wire adapters to core logic; keep them thin. |

## Quality gate flow

```
Claude edits a .py file  -> PostToolUse hook: ruff format (that file only)
Claude stops             -> Stop hook: if .py files changed, run the gate; exit 2 = keep working
git commit               -> pre-commit: the gate on staged files
push / pull request      -> CI: uv sync --locked, then the gate on all files (Python 3.11 and 3.14)
```

The gate itself is defined once, in `.pre-commit-config.yaml`. The Stop hook and CI only call it.

## Design decisions

- **One gate definition.** The pre-commit config is the only list of checks. The Stop hook and CI
  run `pre-commit run --all-files`, so the three can't drift apart.
- **Tool versions come from `uv.lock`.** The local pre-commit hooks use `language: unsupported`
  (the new name for `system`) and call `uv run <tool>`, so ruff, pyright and pytest aren't
  pinned a second time in the pre-commit config.
- **The edit hook formats but never lint-fixes.** `ruff check --fix` would delete an import
  that Claude adds one edit before its first use.
- **The Stop hook is cheap and can't loop.** It only runs when `.py` files changed. The
  `stop_hook_active` flag allows at most one forced continuation per stop.
- **Coverage runs only in the gate** (`pytest --cov`), not in `addopts`. Running a single test
  file must not fail on the coverage threshold.
- **Function length is checked by an AST test.** ruff has no rule for function lines;
  `tests/test_code_rules.py` has one.

## M1 data flow

```
gt data download/update -> cli.py -> data_sync.py (retry, batching, SyncReport)
                                        |         \
                                  yahoo.py         price_store.py
                              (yfinance adapter)  (parquet, atomic write)
                                        |
                                  cleaning.py (pure OHLCV rules)
```

`cli.py` looks up `yahoo.fetch_batch` and `time.sleep` at call time (not by importing the bound
function), so tests can monkeypatch them. `data_sync.py` takes both as injected parameters
(`FetchFn`, `SleepFn`) and has no I/O of its own, which is what makes its retry, batching and
re-adjustment logic (D13, see [spec-common.md](spec-common.md#1-decisions-beyond-the-prd)) unit
-testable without a network. Ticker universe and data layout: [docs/data.md](data.md).

## M2 data flow

```
gt app -> cli.py -> ui/root.py (root(), header, theme resolution)
                          |
                    ui/play.py (pick_random_chart, PriceStore)
                          |
                    indicators.py -> chart.py (decision_window, build_figure)
                          |
                    ui/chart_panel.py (preset buttons + ui.plotly)
```

`decision_window` drops the `date` column and re-indexes to an integer `x` relative to the decision
day, so nothing downstream (chart, JSON sent to the browser) can leak the real date. `chart.py`
converts every trace array to a plain Python list before handing it to plotly; pandas/numpy-backed
arrays make plotly 7 emit base64-encoded `bdata` blocks instead of plain JSON, which is harder to
inspect and unnecessary at this data size. `ui/chart_panel.py` and `ui/root.py` each carry one
`# pyright: ignore[reportUnknownMemberType]` for a NiceGUI 3.17.1 stub gap (`ui.run`'s bare
`Callable` parameter, `update_figure`'s reference to plotly's unstubbed `Figure`), both verified in
isolation to be library-stub limitations, not application code.

## M3 trading rules

```
trading.py: make_card(s) -> Card (fixed at Tag 0)
                                |
                          simulate(_all) -> TradeResult (R6 exit rules)
                                |
                option_values -> points/label/book/k_locked (R7-R9)
```

Pure module, no pandas and no I/O (D1: `decimal.Decimal` throughout, `dec(x) = Decimal(repr(x))`).
Callers (M4 pool, M6 game) pass plain lists of `(open, high, low, close)` float tuples for `future`
and never re-implement a rule. The card is fixed once at Tag 0; `simulate` reuses `card.d`,
`card.stake` and `card.fee` unchanged even when the entry price differs from P0. `exit_on_day`
checks gap exits (KO, SL, TP, in that order) only from day 2 onward, then intraday SL/TP for every
day — the entry day can't gap against its own opening price.

## M4 snapshot pool

```
gt snapshots build -> cli.py -> pool.py: build_pool
                                    |            \
                          eligibility.py      signals.py
                          (R10 candidate mask) (R11 event flags)
                                    |
                          select (deterministic, seeded)
                                    |
                          snapshot_row -> trading.py (make_cards, simulate_all, option_values)
                                    |
                              pool_store.py (snapshots.parquet + snapshots.json, atomic)
```

`build_pool` runs in three phases: gather per-ticker candidate indices (vectorized, only the small
`idx`/`is_signal` arrays are kept, not the full bars), select `N` of them deterministically, then
recompute indicators/flags only for the selected tickers to build rows. numpy's own stubs are
ambiguous for `cumsum`, `where`, `flatnonzero`, `concatenate` and `permutation` under pyright strict
(verified in isolation) — `eligibility.py` and `pool.py` each carry scoped
`# pyright: ignore[reportUnknownMemberType]` comments for these, same class of issue as M2's
NiceGUI/plotly stub gaps. Schema, selection algorithm and the manual full-build results:
[docs/pool.md](pool.md).

## M5 persistence and setup

```
gt app -> cli.py -> ui/root.py: root(), db.init(), PageContext
                          |                    \
                    ui/setup.py           ui/play.py (hint if ctx.active_user() is None)
                    (SetupView.render())        |
                          |                ui/chart_panel.py (now takes ctx, uses ctx.dark)
                    settings_rules.py (pure validation)
                          |
                       db.py (SQLite: users, resets, app_state)
```

`Database.__init__` does no disk I/O; `db.init()` (called once from `root()`) creates `data/app.db`'s
three tables if missing and sets `PRAGMA user_version`. Every other `Database` method opens and
closes its own connection (`contextlib.closing`, `row_factory = sqlite3.Row`, `PRAGMA foreign_keys
= ON`), which is simple and fast enough for the single-user case. Validation happens twice by
design: `settings_rules.py` produces the German UI error messages, and the table's own `CHECK`
constraints are the last line of defense (e.g. `balance_cents >= 0`).

```sql
users (id, name, name_key UNIQUE, start_capital_cents, balance_cents, lev_mid, lev_pro,
       interest_tenths, fee_tenths, created_at)
resets (id, user_id, at, balance_before_cents)
app_state (key PRIMARY KEY, value)   -- holds 'active_user_id'
```

`PageContext` (`ui/context.py`) is a non-frozen dataclass (needed for NiceGUI's
`bind_text_from(ctx, "user_name")`, which requires a plain mutable attribute) carrying `cfg`, `db`,
`dark` and the header's `user_name`. `chart_panel` and `play_page` take `ctx` instead of `dark`
directly, so M6 can extend them without changing their signatures again.

## M6 game rounds

```
gt app -> ui/play.py: PlayPage.render()
              |
     draw/current round (GameService, game_service.py)
              |         \
        DecisionView    ResolutionView
        (open round)    (done round)
              |               |
      game.py: decision_cards  game.py: resolve (deterministic replay)
      chart.py: build_figure   chart.py: build_resolution_figure
      + add_preview                + signal_flags, EVENT_LABELS
              |
     "Entscheidung bestätigen" -> GameService.confirm
              |
     db.py: confirm_round (one transaction: read balance, compute
             outcome, write rounds + users, or roll back)
```

`GameService.confirm` reads the user's balance *inside* `Database.confirm_round`'s transaction,
never the value the page last rendered — a second confirmation (double click, stale tab) finds the
round already `status = 'done'` and books nothing. `game.resolve` is the single source of truth for
both booking (via `confirm`) and later replay (via `resolution`): the resolution view recomputes the
outcome from the round's *stored* settings (`setting_of_round`) rather than reading them back from
the DB's other columns, so the table the player sees always matches what was booked.

Leak-proofing carries over from M2: `DecisionView` never puts the ticker, company name or `t0` into
any element prop, marker, table row key, notification or the page itself before confirmation —
`chart.py`'s `decision_window` already drops the `date` column, and `ui/play.py` only reveals
`service.name_of(ticker)` and `date_de(t0)` inside `ResolutionView`, after `rnd.status == "done"`.

`chart_panel(ctx, window, make_figure, presets)` takes an explicit `window` alongside the figure
factory (a deviation from the spec's `chart_panel(ctx, make_figure, presets)` — see
[IMPLEMENTATION.md](../IMPLEMENTATION.md) §4): preset buttons call `apply_preset(fig, window,
name)`, which needs the source DataFrame, not just a already-built `Figure`. `make_figure` still
carries the caller's per-theme figure logic, so `DecisionView`'s closure adds the preview overlay
and `ResolutionView`'s closure calls `build_resolution_figure` unchanged.

## M6.1 desktop layout

One markup, no separate build or device detection: Tailwind's `lg:` breakpoint (1024 px, already
used since M2 for the option-card grid) switches the layout, so both the stacked (< 1024 px) and
the desktop (≥ 1024 px) rules ship in the same `classes(...)` string and the browser's media query
picks one. `DecisionView._build` wraps the chart and the option/confirm column in a
`flex flex-col lg:flex-row` div (`decision-chart-pane` ≈64 %, `decision-options-pane` ≈36 %,
markers used by `tests/test_ui_play.py`); `chart_panel`'s `ui.plotly` grows from `h-[420px]` to
`lg:h-[720px]`. `SetupView.render` pairs its four cards into two `grid grid-cols-1 lg:grid-cols-2`
rows (`setup-row-1`/`setup-row-2`). None of this touches `game.py`, `trading.py` or the M6
round-lifecycle logic — it is CSS classes on existing containers only, verified by asserting the
rendered elements' classes in the `User` fixture (NiceGUI's test client doesn't evaluate media
queries, so there is no way to assert the *applied* layout without a real browser).

Manual check (2026-09-22, headless Chromium via Playwright) caught a real bug this class-only
testing can't: Quasar's own `.flex` utility also sets `flex-wrap: wrap`, colliding with Tailwind's
`.flex` (no wrap); at ≥1024 px the two panes computed `flex-direction: row` but still wrapped onto
separate lines because their combined width slightly exceeded the container. Fixed by adding
`lg:flex-nowrap` to `decision-layout`'s classes, and added an assertion for that class next to the
existing ones so a future edit can't silently drop it. Any new side-by-side `flex` row built with
Tailwind's `flex`/`lg:flex-row` on a plain `ui.element` needs the same explicit `flex-nowrap` —
verify with a real browser (`getComputedStyle(...).flexWrap`), not just the class list, since the
class being present doesn't guarantee it wins the cascade against Quasar's own rules.

### Selected-card frame and the resolution grid (2026-09-22)

Two small UI follow-ups on M6.1, both CSS-only in `theme.py`'s `page_css()` (split into
`_tokens_css()`/`_resolution_grid_css()` to stay under the 50-line function limit):

- `.gt-selected` (already applied by `DecisionView._option_card` via `card_lines`'s caller, but
  previously undefined) now draws a `--gt-up`-colored border and glow, so the picked option card is
  visibly marked before confirming.
- `ResolutionView` no longer renders as one stacked column; it uses a named-area CSS Grid
  (`.gt-resolution-grid`, areas `tiles`/`chart`/`result`/`next`/`stats`) that is single-column by
  default and switches to `chart` (left, spanning all rows) + a `tiles → result → next → stats`
  right column at the same ≥1024 px breakpoint as M6.1 — unlike the flex-based decision layout,
  grid template areas control visual position independently of DOM order, so the mobile stacking
  order (tiles, chart, table, next-round button, stats — unchanged from M6) doesn't have to match
  the desktop visual order. `_tiles`/`_stats_card` moved from `PlayPage` methods to module-level
  functions in `play.py` so both `PlayPage` (decision view) and `ResolutionView` can call them
  without pyright's `reportPrivateUsage`. Manual check: headless Chromium confirmed the green frame
  renders and the five grid areas' bounding boxes sit in two real columns at 1440 px, one at 390 px.

### Gamified result badge (2026-09-23)

UI polish requested for the resolution screen, no PRD change. `game.badge_tier(*, neutral, optimal,
points)` is a pure function (tested in isolation, not via a full `Resolution`) mapping the chosen
option's outcome to one of four tiers: `neutral` (no option beat the reference), `optimal` (the
chosen option was among the best), `gut` (points ≥ 50 but not optimal), `schlecht` (below 50).
`ResolutionView._badge` renders it as a `.gt-badge-<tier>` chip (icon + German label) above the
result table. CSS in `theme.py`'s new `_badge_css()` (split out for the 50-line limit, added to
`page_css()`) gives every badge a pop-in animation on mount and an extra glow pulse for `optimal`;
the resolution tiles pane also gets the pop-in class. No JS-driven number count-up: NiceGUI's test
simulation doesn't execute client JS, so that would have been unverifiable by the automated suite —
CSS keyframe animation was chosen instead, verified structurally by
`test_resolution_shows_result_badge` (marker + tier class + matching label); the animation's actual
motion still needs a manual browser check, same class of gap as M6.1's screenshots.

## Known limits

- `pre-commit run --all-files` checks only files git tracks. New untracked files are formatted by
  the edit hook, and pyright and pytest cover the whole project. ruff lint reaches new files at
  commit time.
- gitleaks scans staged changes, so it protects commits but CI doesn't rescan history.
  Contributors must run `uv run pre-commit install`.
- Claude Code permission rules are not a security boundary. `Read(.env)` stops the Read tool,
  not every shell command. Keep real secrets out of the repo directory where you can.
