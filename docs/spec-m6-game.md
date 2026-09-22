# Implementation spec M6: game mode

PRD: §4 M6 (plus R1–R9). Common rules: [spec-common.md](spec-common.md) (D7, D9).
Result: complete rounds on the pool: draw → decision → confirmation → resolution → next round.

## 1. Files

| Create / change | Content |
|---|---|
| `src/app/db.py` | schema v2: `rounds` table, round methods, `stats` |
| `src/app/universe.py` | `ticker_names()` (cached) |
| `src/app/game.py` | pure: draw, settings, cards text, resolution, DB outcome |
| `src/app/game_service.py` | orchestration with DB, pool, prices |
| `src/app/chart.py` | `add_preview`, `resolution_window`, `build_resolution_figure`, `Figure` alias |
| `src/app/ui/chart_panel.py` | takes a figure factory; presets optional |
| `src/app/ui/play.py` | `PlayPage`, `DecisionView`, `ResolutionView`, tiles, statistics |
| `tests/helpers.py` | `make_game_env` |

## 2. Design

### 2.1 Database additions (`db.py`, `SCHEMA_VERSION = 2`)

```sql
CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  snapshot_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  t0 TEXT NOT NULL,                        -- ISO date
  status TEXT NOT NULL CHECK (status IN ('open', 'done')),
  level TEXT, leverage INTEGER, fee_tenths INTEGER, interest_tenths INTEGER,
  option TEXT, v REAL, pnl_cents INTEGER, fee_cents INTEGER, financing_cents INTEGER,
  points INTEGER, balance_before_cents INTEGER, balance_after_cents INTEGER,
  created_at TEXT NOT NULL, confirmed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_round ON rounds(user_id) WHERE status = 'open';
```

```python
@dataclass(frozen=True)
class RoundRow:                     # all columns; confirmation fields are None while open
    id: int; user_id: int; snapshot_id: str; ticker: str; t0: date; status: str
    level: str | None; leverage: int | None; fee_tenths: int | None; interest_tenths: int | None
    option: str | None; v: float | None; pnl_cents: int | None; fee_cents: int | None
    financing_cents: int | None; points: int | None
    balance_before_cents: int | None; balance_after_cents: int | None
    created_at: str; confirmed_at: str | None

@dataclass(frozen=True)
class Stats:
    rounds: int; points_total: int; points_avg: float; optimal_share: float
    balance_cents: int; start_capital_cents: int; resets: int

# Database methods
def open_round(self, user_id: int) -> RoundRow | None
def last_round(self, user_id: int) -> RoundRow | None          # highest id
def insert_open_round(self, user_id: int, snapshot_id: str, ticker: str, t0: date, now: str) -> RoundRow
def play_counts(self, user_id: int) -> dict[str, int]           # rounds per snapshot_id (open + done)
def confirm_round(self, round_id: int, user_id: int,
                  outcome: Callable[[int], RoundOutcome], now: str) -> bool
def stats(self, user_id: int) -> Stats                          # optimal_share = points == 100 (D9)
```

`confirm_round`, exactly once, in one `with conn:` transaction:

1. Read the round; unless `status == 'open'` and it belongs to the user → return False.
2. `before = users.balance_cents`; `o = outcome(before)` (pure computation, see `game.outcome`).
3. `UPDATE rounds SET status='done', …confirmation fields…, confirmed_at=? WHERE id=? AND status='open'`.
   If `rowcount != 1`, raise an internal exception so `with conn` rolls back → return False.
4. `UPDATE users SET balance_cents = o.balance_after_cents` → return True.

A second confirmation (double click, second tab) therefore finds `status='done'` and books nothing.

### 2.2 `game.py` (pure)

```python
@dataclass(frozen=True)
class PoolEntry:
    snapshot_id: str; ticker: str; t0: date; label: str        # label = label_l1

def draw_snapshot(entries: Sequence[PoolEntry], play_counts: Mapping[str, int],
                  rng: random.Random, exclude: AbstractSet[str] = frozenset()) -> PoolEntry | None:
    """Among non-excluded entries with the minimum play count: choose a label uniformly among the
    labels present (sorted for determinism), then an entry uniformly within that label.
    None if no entry is left."""

@dataclass(frozen=True)
class Setting:
    level: Level; leverage: int; costs: Costs; balance: Decimal; start_capital: Decimal

def setting_for(user: UserRow, level: Level) -> Setting            # current user values
def setting_of_round(rnd: RoundRow, start_capital_cents: int) -> Setting   # stored values of a done round
def costs_of(fee_tenths: int, interest_tenths: int) -> Costs       # tenths / 1000 as Decimal

@dataclass(frozen=True)
class SnapshotBars:
    p0: float; atr: float; future: list[list[float]]     # future = 120 bars (open, high, low, close)

def decision_cards(snap: SnapshotBars, s: Setting) -> dict[OptionCode, Card]   # make_cards with s.balance
def card_lines(card: Card, s: Setting) -> list[str]     # German, see §2.5
def wait_lines(horizon: int) -> list[str]               # ["Warten 30 Tage", "Kein Einsatz, keine Kosten"]

@dataclass(frozen=True)
class OptionOutcome:
    option: OptionCode; value: float; amount: Decimal      # amount = V * reference balance
    reason: ExitReason | None; costs: Decimal; points: int; optimal: bool   # W: reason None, costs 0

@dataclass(frozen=True)
class Resolution:
    setting: Setting; chosen: OptionCode; neutral: bool
    outcomes: dict[OptionCode, OptionOutcome]; results: dict[int, TradeResult]
    pnl: Decimal; fee: Decimal; financing: Decimal        # of the chosen option; 0 for W
    balance_after: Decimal

def resolve(snap: SnapshotBars, s: Setting, chosen: OptionCode) -> Resolution:
    """ref = value_balance(s.balance, s.start_capital) (D7); cards = make_cards(p0, atr, ref, L, costs);
    results = simulate_all; values = option_values(results, ref); points/optimal from trading;
    chosen K while k_locked -> ValueError; balance_after = book(s.balance, chosen, pnl)."""

@dataclass(frozen=True)
class RoundOutcome:            # ints and strings for the DB
    level: str; leverage: int; fee_tenths: int; interest_tenths: int; option: str; v: float
    pnl_cents: int; fee_cents: int; financing_cents: int; points: int; balance_after_cents: int

def outcome(res: Resolution, fee_tenths: int, interest_tenths: int) -> RoundOutcome
def round_number(done_rounds: int, has_open: bool) -> int         # tile "Runde": done + 1 while open
```

With B ≥ 1 % of the start capital, ref = B, so the K cards shown and the simulation use the same M.

### 2.3 `game_service.py` (orchestration)

```python
class PoolMissingError(RuntimeError): ...

@dataclass(frozen=True)
class RoundData:
    ind: pd.DataFrame; t0_idx: int; snap: SnapshotBars

class GameService:
    def __init__(self, cfg: Config, db: Database, rng: random.Random | None = None,
                 now: Callable[[], str] = utc_now) -> None
    def pool_entries(self) -> list[PoolEntry]            # cached read; PoolMissingError if the file is missing
    def current(self, user_id: int) -> RoundRow | None   # open round, else last round, else None
    def start_round(self, user_id: int) -> RoundRow
    def load(self, ticker: str, t0: date) -> RoundData
    def confirm(self, user: UserRow, rnd: RoundRow, level: Level, option: OptionCode) -> bool
    def resolution(self, rnd: RoundRow, user: UserRow) -> Resolution   # done round, from stored values
    def name_of(self, ticker: str) -> str                # universe.ticker_names().get(ticker, ticker)
```

- Pool cache: module-level `functools.lru_cache` on `(path, mtime_ns)` → list of `PoolEntry` from
  the columns `snapshot_id, ticker, t0, label_l1`.
- `start_round`: `draw_snapshot` with `db.play_counts`; try `load(entry.ticker, entry.t0)`; on
  `FileNotFoundError` or a missing t0 in the price file: `logger.warning("Snapshot %s übersprungen:
  Kursdatei fehlt", id)`, add it to `exclude`, draw again. When nothing is left: `PoolMissingError`.
  Then `db.insert_open_round`.
- `load`: `PriceStore.read(ticker)` → `with_indicators` → `t0_idx` = row whose date == t0 →
  `SnapshotBars(close[t0_idx], atr14[t0_idx], ohlc rows t0_idx+1 … t0_idx+120)`.
- `confirm`: `db.confirm_round(rnd.id, user.id, lambda cents: game.outcome(game.resolve(snap,
  replace(setting_for(user, level), balance=Decimal(cents) / 100), option), user.fee_tenths,
  user.interest_tenths), now())`.
- `resolution`: `resolve(snap, setting_of_round(rnd, user.start_capital_cents), Option(rnd.option))`.
  This is deterministic, so the table always matches the booking.
- Call `universe.ticker_names()` as a module attribute at call time (tests monkeypatch it).

### 2.4 Chart additions (`chart.py`)

```python
Figure = go.Figure            # re-export so UI modules can annotate without importing plotly

def add_preview(fig: go.Figure, option: OptionCode, card: Card | None, theme: Theme) -> None:
    """K: horizontal line traces over x in [0, H]: "Vorschau SL" (theme.down) at card.sl_price,
    "Vorschau TP" (theme.up) at tp_price, and "Vorschau KO" (theme.muted, dotted) if ko_price.
    W: fig.add_vline(x=H, line_dash="dash", annotation_text=f"Tag {H}").
    Extend the x range's right edge to H + 0.5 (all prices on P0 basis)."""

def resolution_window(ind: pd.DataFrame, t0_idx: int) -> pd.DataFrame:
    """Rows max(0, t0_idx-1259) .. t0_idx+120, x = row - t0_idx (… 0 … 120), without date."""

def build_resolution_figure(window: pd.DataFrame, theme: Theme, res: Resolution) -> go.Figure:
    """build_figure + add_vrect(x0=0.5, x1=120.5, fillcolor=theme.accent, opacity=0.08, line_width=0)
    + add_vline(x=0, line_dash="dot"); chosen K: marker traces "Einstieg" (1, E) and
    "Ausstieg" (n, exit price) with text = German exit reason; chosen W: add_vline at H.
    x range (-251.5, 120.5)."""

EXIT_LABELS = {TP: "Take-Profit", SL: "Stop-Loss", KO: "Knock-out", TIME: "Zeit"}
```

`chart_panel(ctx, make_figure: Callable[[Theme], Figure], presets: bool)`: presets rebuild with
`apply_preset`; a theme change rebuilds via `make_figure(theme_for(...))`. The decision view passes
a closure that also applies the current preview.

### 2.5 UI (`ui/play.py`)

```
PlayPage(ctx).render():               # container.clear() + rebuild; called after confirm / next round
  no user          -> hint + link "Zum Setup" (M5)
  PoolMissingError -> "Kein Snapshot-Pool gefunden. Bitte zuerst `gt snapshots build` ausführen."
  rnd = service.current(user.id) or service.start_round(user.id)
  tiles(user, stats)                  # "Guthaben", "Punkte gesamt", "Runde"
  rnd.status == "open" -> DecisionView(page, user, rnd)
  else                 -> ResolutionView(page, user, rnd)
  stats_card(stats)
```

**DecisionView** (state: `level = Level.EINFACH`, `selected: OptionCode | None = None`)

- `ui.toggle(["Einfach", "Mittel", "Profi"], value="Einfach").mark("level")`. A change recomputes
  the cards from the current DB user (`setting_for`), clears the selection, and redraws the chart
  without a preview.
- Chart: `chart_panel` with presets on `decision_window(ind, t0_idx)`.
- Row "Kaufen": 3 cards (`.gt-card`) with `card_lines`; row "Warten": 3 cards with `wait_lines`.
  Each card has a button "Auswählen" marked `pick-<CODE>`. The selected card gets the class
  `gt-selected` (CSS: 2 px outline in `--q-primary`).
- `k_locked(balance, start)`: disable the K buttons (`.disable()`) and show the label
  "Guthaben unter 1 % des Startkapitals: Kaufoptionen gesperrt." plus `ui.link("Zum Setup", "/setup")`.
- Button "Entscheidung bestätigen" (marked `confirm`) is disabled until something is selected.
  Click → disable it first → `service.confirm(...)` → `page.render()`.

`card_lines` for a K card (German, via `fmt`); lines with L = 1 omit financing and KO:

```
"K30 · 30 Tage · Profi"
"SL -5,00 % → 95,00 · TP +10,00 % → 110,00 · CRV 1 : 2"
"Einsatz 2.000,00 € (20,00 % von B) · Hebel 10 · Exposure 20.000,00 €"
"Stückzahl ≈ 200 · Gebühr 40,00 €"
"Finanzierung (30 Tage) 107,14 € · KO-Abstand -10,00 %"
"Verlust bei SL 1.040,00 € · Gewinn bei TP 1.960,00 €"
```

**ResolutionView** (the done round `rnd`)

- Reveal line: `f"{name} ({ticker}) · Tag 0: {date_de(t0)}"`; then signal list:
  `signal_flags(ind).iloc[t0_idx]` → the `EVENT_LABELS` of the true events, or "Keine
  Signal-Ereignisse an Tag 0.".
- Chart: `chart_panel` (no presets) with `build_resolution_figure`.
- `ui.table` (`row_key="option"`), columns "Option", "Wert %", "Wert €", "Exit", "Kosten", "Punkte",
  "Markierung" ("Ihre Wahl", "optimal", both joined with " · "). Neutral round: the label
  "Keine Option war vorteilhaft".
- "Guthaben vorher … → nachher …", "Punkte dieser Runde: n", "Punkte gesamt: m".
- Button "Nächste Runde" → `service.start_round(user.id)` → `page.render()`.

Layout: tiles `flex flex-col md:flex-row gap-4`; card rows `grid grid-cols-1 md:grid-cols-3 gap-4`
(Tailwind md = 768 px, so it stacks below that width).

## 3. Tests

`make_game_env(root, tickers=("ZZA", "ZZB", "ZZLEAK"), n=30, seed=1)` in helpers: `write_store`
with random-walk tickers of 1,600 bars → `build_pool` → `write_pool` to the config paths → create the
user "Test" (defaults). UI tests also monkeypatch `universe.ticker_names` to
`{"ZZLEAK": "Leckprüfung AG", …}`.

| File | Test | Asserts |
|---|---|---|
| `test_game.py` | draw strata | 6 labels × 10 entries, `random.Random(7)`, 600 draws, incrementing counts → each label 60–140 times; the first 60 draws are all different |
| | draw least played | all counts 1 except one entry with 0 → that entry |
| | exhausted pool repeats | 60 draws on 60 entries, then the 61st comes from the count-1 set |
| | exclude | every entry excluded → None |
| | resolve matches trading | a fixed `SnapshotBars` → outcomes equal `trading` on the same inputs (values, points, optimal) |
| | W books nothing | `balance_after == balance`, pnl 0 |
| | K locked | balance 99 €, start 10,000 € → resolve with K30 raises `ValueError`; with W30, values are computed on 10,000 € (D7) |
| | card_lines | worked example K30 Profi → exactly the 6 lines in §2.5; K30 Einfach → no line with "Finanzierung" |
| `test_db_rounds.py` | migration v1 → v2 | a v1 file (M5 schema, `user_version` 1, one user) → `init()` → version 2, `rounds` exists, user kept |
| | one open round | a second `insert_open_round` for the same user → `IntegrityError` |
| | confirm once | `confirm_round` twice → True then False; balance changed once; the outcome callable ran once |
| | play counts, stats | counts per snapshot; `optimal_share` counts only points == 100 |
| `test_game_service.py` | booking with user values | user lev 3/7, fee 1.5 %, interest 4.0 %; confirm K30 at Profi → stored leverage 7, fee_tenths 15, interest_tenths 40, and pnl, points, balance_after equal the M3 functions on the same bars |
| | open round survives restart | `start_round`, then a new `GameService` and `Database` on the same dir → `current()` returns the same `snapshot_id` |
| | missing price file skipped | delete ZZB's parquet → 20 `start_round` calls never return ZZB; caplog contains "übersprungen" |
| | pool missing | no parquet → `PoolMissingError` |
| | resolution deterministic | `resolution()` equals the stored v, pnl and points |
| `test_chart.py` (extend) | preview K Profi | 3 traces "Vorschau SL/TP/KO" with y constant at the card prices, x [0, H]; x range right edge H + 0.5 |
| | preview K Einfach | no "Vorschau KO" |
| | preview W | one vline shape at x = H |
| | resolution figure | last x == 120; a rect shape from 0.5; "Einstieg" at x = 1 |
| `test_ui_play.py` | leak before confirmation | `make_game_env` with the single ticker ZZLEAK → `rendered_text(user)` contains none of "ZZLEAK", "Leckprüfung AG", `t0` as `YYYY-MM-DD` or `DD.MM.YYYY`, and no `\d{4}-\d{2}-\d{2}` at all |
| | reveal after confirmation | pick W10, confirm → all three are visible |
| | reload keeps the round | open "/" twice → same open round id in the DB |
| | confirm is final | after confirm the "confirm" marker is gone; open "/" again → resolution shown, balance unchanged, 1 done round |
| | level change | select "Profi" → should_see "Hebel 10"; pick K30, confirm → stored level "Profi", leverage 10 |
| | settings change while open | `update_settings(lev_pro=15)`, reopen "/", select "Profi" → "Hebel 15" |
| | K locked | balance 99 € (raw SQL) → `pick-K10` disabled; should_see "Kaufoptionen gesperrt" |
| | next round | after confirm, click "Nächste Runde" → a new open round with a different snapshot |
| | pool missing | should_see "gt snapshots build" |

## 4. Steps

1. DB schema v2 and round methods (red → green).
2. `game.py` (red → green).
3. `game_service.py` (red → green).
4. Chart additions (red → green).
5. `ui/play.py`: first the leak and confirm-once tests, then the rest (red → green).
6. Gate, docs (`docs/architecture.md` data flow of a round; README "Spielen").
7. Manual (outside the gate, report the results):
   - warm cache: "Nächste Runde" to a finished chart ≤ 2 s; resolution ≤ 1 s;
   - 20 rounds per level without errors;
   - usable in a phone-width browser (≤ 400 px, DevTools device mode);
   - screenshots in light and dark under `docs/ui/` (commit them; the references stay ignored).

## 5. Pitfalls

- Leaks come from details: never put the ticker, name or t0 into element props, marks, table
  row keys, notifications, the URL or the page title before confirmation. The leak test dumps
  every prop.
- The decision view uses `decision_window` (no date column); only the resolution view reads dates.
- `confirm` must read the balance inside the transaction (§2.1); don't pass the balance the page
  showed.
- `ui.toggle` values are the German level names: map them with `Level(value)`.
- Card buttons for K must stay disabled when locked, even though `resolve` also raises.
