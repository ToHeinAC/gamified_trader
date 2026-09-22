# IMPLEMENTATION

Current state of the code, and the only place for phase status. What and why: [PRD.md](PRD.md).
Rules: [AGENTS.md](AGENTS.md). Design: [docs/architecture.md](docs/architecture.md).

## 1. Run and verify

| Task | Command |
|---|---|
| Install (once per clone) | `uv sync && uv run pre-commit install` |
| Tests (fast loop) | `uv run pytest` or `uv run pytest tests/test_core.py` |
| Full gate | `uv run pre-commit run --all-files` |

## 2. Phase status

One row per PRD milestone. Status: `planned`, `in progress`, `done`. Implementation specs for
Release 1: start with [docs/spec-common.md](docs/spec-common.md), then the milestone's spec.

| Phase | Milestone | Status | Verified by | Spec |
|---|---|---|---|---|
| 0 | Blueprint skeleton (no PRD milestone) | done | full gate green | — |
| 1 | M1: Kursdaten und Universum | planned | acceptance tests M1 | [M1](docs/spec-m1-data.md) |
| 2 | M2: Indikatoren, Chart und App-Grundgerüst | planned | acceptance tests M2 | [M2](docs/spec-m2-chart-app.md) |
| 3 | M3: Handelsvorschläge, Simulation und Bewertung | planned | acceptance tests M3 | [M3](docs/spec-m3-trading.md) |
| 4 | M4: Snapshot-Pool (50.000) | planned | acceptance tests M4 | [M4](docs/spec-m4-pool.md) |
| 5 | M5: Persistenz und Setup-Modus | planned | acceptance tests M5 | [M5](docs/spec-m5-setup.md) |
| 6 | M6: Spielmodus | planned | acceptance tests M6 | [M6](docs/spec-m6-game.md) |
| 7 | M7: Features und ML-Modell (preliminary) | planned | after PRD iteration | — |
| 8 | M8: Entdeckungsmodus (preliminary) | planned | after PRD iteration | — |
| 9 | M9: Lernmodus (preliminary) | planned | after PRD iteration | — |

## 3. Module map

| Module | Responsibility |
|---|---|
| `src/app/core.py` | Example of pure logic (`slugify`). Replace it with your own. |
| `tests/conftest.py` | Shared fixtures; blocks network access in all tests. |
| `tests/test_code_rules.py` | Enforces functions ≤ 50 lines in `src/`, `tests/`, `.claude/hooks/`. |
| `tests/test_docs.py` | Enforces doc size limits and resolvable local links. |
| `.claude/hooks/format_on_edit.py` | PostToolUse hook: ruff-formats each `.py` file Claude edits. |
| `.claude/hooks/stop_gate.py` | Stop hook: runs the gate if `.py` files changed; blocks the stop on failure. |

## 4. Open issues

- [PRD.md](PRD.md) v0.2: grill-me settled A1–A18 (Release 1 is ready to implement). A19 and A20
  stay open and must be settled in a separate PRD iteration before M7 starts.
- Spec decision D13 ([docs/spec-common.md](docs/spec-common.md) §1): `gt data update` after a
  split or dividend needs the user's decision before it changes from plain appending.
