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

## Known limits

- `pre-commit run --all-files` checks only files git tracks. New untracked files are formatted by
  the edit hook, and pyright and pytest cover the whole project. ruff lint reaches new files at
  commit time.
- gitleaks scans staged changes, so it protects commits but CI doesn't rescan history.
  Contributors must run `uv run pre-commit install`.
- Claude Code permission rules are not a security boundary. `Read(.env)` stops the Read tool,
  not every shell command. Keep real secrets out of the repo directory where you can.
