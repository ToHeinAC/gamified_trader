# Implementation spec M5: persistence and setup mode

PRD: §4 M5. Common rules: [spec-common.md](spec-common.md).
Result: SQLite `data/app.db` with users, settings, resets and the active user; page "Setup".
Rounds follow in M6.

## 1. Files

| Create / change | Content |
|---|---|
| `src/app/config.py` | `db_path` property (`data_dir / "app.db"`) |
| `src/app/settings_rules.py` | validation (pure) |
| `src/app/fmt.py` | German formatting (pure) |
| `src/app/db.py` | `Database` (adapter) |
| `src/app/ui/context.py` | `PageContext` (per client) |
| `src/app/ui/root.py` | create `PageContext`, nav "Setup", user name in the header |
| `src/app/ui/setup.py` | page "Setup" |
| `src/app/ui/play.py` | hint when no user exists |

## 2. Design

### 2.1 `settings_rules.py` (pure)

```python
class ValidationError(ValueError): ...      # str(e) is the German message shown in the UI

NAME_MAX = 40
CAPITAL_MIN, CAPITAL_MAX, CAPITAL_DEFAULT = 1_000, 1_000_000, 10_000
LEV_MIN, LEV_MAX = 2, 20
LEV_MID_DEFAULT, LEV_PRO_DEFAULT = 5, 10
INTEREST_MAX_PCT, FEE_MAX_PCT = 20.0, 10.0
INTEREST_DEFAULT_TENTHS, FEE_DEFAULT_TENTHS = 50, 20

@dataclass(frozen=True)
class UserSettings:
    start_capital_eur: int
    lev_mid: int
    lev_pro: int
    interest_tenths: int     # 5.0 % -> 50
    fee_tenths: int          # 2.0 % -> 20

def name_key(name: str) -> str                                   # name.strip().casefold()
def validate_name(raw: str, existing: Iterable[str]) -> str      # returns the trimmed name
def validate_start_capital(value: float | None) -> int
def validate_leverage(mid: float | None, pro: float | None) -> tuple[int, int]
def validate_rate(value: float | None, max_pct: float, message: str) -> int   # returns tenths
def validate_settings(capital: float | None, mid: float | None, pro: float | None,
                      interest: float | None, fee: float | None) -> UserSettings
```

- `ui.number` delivers `float | None`, so accept floats. An integer check is
  `value is not None and float(value).is_integer()`.
- Rate: `tenths = round(value * 10)`; reject if `abs(value * 10 - tenths) > 1e-9` or the value is
  outside `[0, max]`.
- Messages (exact text, the UI tests look for them):
  - `"Name muss 1–40 Zeichen lang sein."`
  - `"Name ist bereits vergeben."`
  - `"Startkapital muss eine ganze Zahl von 1.000 bis 1.000.000 € sein."`
  - `"Hebel müssen ganze Zahlen von 2 bis 20 sein, Mittel ≤ Profi."`
  - `"Zinssatz muss zwischen 0,0 und 20,0 % liegen (Schritte 0,1)."`
  - `"Gebührensatz muss zwischen 0,0 und 10,0 % liegen (Schritte 0,1)."`

### 2.2 `fmt.py` (pure)

```python
def eur(amount: Decimal) -> str          # Decimal("10000") -> "10.000,00 €"; negative -> "-1.247,14 €"
def cents_eur(cents: int) -> str         # eur(Decimal(cents) / 100)
def pct(v: float, signed: bool = True) -> str   # 0.016 -> "+1,60 %"; -0.124714 -> "-12,47 %"; 0 -> "0,00 %"
def price(x: Decimal) -> str             # "97,85" (no currency, 2 places)
def qty(x: Decimal) -> str               # "≈ 20" (rounded to an integer; "≈ 0,5" below 1)
def date_de(d: date | pd.Timestamp) -> str   # "31.12.2024"
def points(n: int) -> str                # 1240 -> "1.240"
```

Implement with `f"{x:,.2f}"`, then swap `,` and `.`.

### 2.3 `db.py` (adapter)

```python
SCHEMA_VERSION = 1   # M6 raises it to 2 when it adds the rounds table

@dataclass(frozen=True)
class UserRow:
    id: int
    name: str
    start_capital_cents: int
    balance_cents: int
    lev_mid: int
    lev_pro: int
    interest_tenths: int
    fee_tenths: int

class Database:
    def __init__(self, path: Path) -> None          # no disk access here
    def init(self) -> None                          # mkdir parent, CREATE TABLE IF NOT EXISTS, PRAGMA user_version
    def schema_version(self) -> int
    def create_user(self, name: str, start_capital_eur: int, now: str) -> int
    def users(self) -> list[UserRow]                # ordered by name_key
    def user(self, user_id: int) -> UserRow | None
    def update_settings(self, user_id: int, s: UserSettings) -> None   # never touches balance
    def reset_balance(self, user_id: int, now: str) -> None            # one transaction, logs a reset
    def reset_count(self, user_id: int) -> int
    def active_user_id(self) -> int | None
    def set_active_user(self, user_id: int) -> None
```

- Connection helper: `contextlib.closing(sqlite3.connect(self.path))`, `row_factory = sqlite3.Row`,
  `PRAGMA foreign_keys = ON`, and `with conn:` for commit or rollback. Open one connection per method
  call; that's simple and fast enough for one user.
- `now` is passed in (ISO 8601 UTC, seconds) so tests are deterministic. The UI passes
  `datetime.now(UTC).isoformat(timespec="seconds")`.
- `create_user` also calls `set_active_user` for the new user (same transaction).

Schema (version 1):

```sql
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  start_capital_cents INTEGER NOT NULL CHECK (start_capital_cents BETWEEN 100000 AND 100000000),
  balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
  lev_mid INTEGER NOT NULL CHECK (lev_mid BETWEEN 2 AND 20),
  lev_pro INTEGER NOT NULL CHECK (lev_pro BETWEEN 2 AND 20 AND lev_mid <= lev_pro),
  interest_tenths INTEGER NOT NULL CHECK (interest_tenths BETWEEN 0 AND 200),
  fee_tenths INTEGER NOT NULL CHECK (fee_tenths BETWEEN 0 AND 100),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resets (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  at TEXT NOT NULL,
  balance_before_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

Validation happens in `settings_rules` first; the CHECKs are the last line of defense (the
acceptance test for B ≥ 0 goes straight to SQL).

### 2.4 UI

```python
# ui/context.py
@dataclass
class PageContext:
    cfg: Config
    db: Database
    dark: ui.dark_mode
    user_name: str = ""          # the header binds to it

    def active_user(self) -> UserRow | None: ...   # db.active_user_id() -> db.user(...)
    def refresh_user_name(self) -> None: ...
```

- `root()`: `cfg = load_config()`, `db = Database(cfg.db_path)`, `db.init()`, build `PageContext`,
  header label `ui.label().bind_text_from(ctx, "user_name")`, nav links "Spielen" and "Setup",
  `ui.sub_pages({"/": lambda: play_page(ctx), "/setup": lambda: setup_page(ctx)})`. `chart_panel`
  and `play_page` now receive `ctx` (use `ctx.dark`).
- `play_page`: if `ctx.active_user()` is None → label "Noch kein Nutzer angelegt." plus
  `ui.link("Zum Setup", "/setup")`, then return.

`ui/setup.py`: a `SetupView` class with a container and `render()`, which clears the container and
rebuilds it. Call it after every successful action. Keep each card builder under 50 lines:

| Card | Elements (German labels are exact; tests use them) |
|---|---|
| "Neuer Nutzer" | `ui.input("Name")`, `ui.number("Startkapital (€)", value=10000, step=1000)`, button "Anlegen", error label |
| "Aktiver Nutzer" | `ui.select({id: name}, value=active_id, label="Nutzer")`; on change → `set_active_user`, `ctx.refresh_user_name()`, `render()` |
| "Einstellungen" (only with an active user) | numbers "Startkapital (€)", "Hebel Mittel", "Hebel Profi", "Zinssatz (% p. a.)", "Gebührensatz (%)"; text "Einfach: Hebel 1 (fest)"; button "Speichern"; error label; note "Neues Startkapital gilt ab dem nächsten Zurücksetzen." |
| "Guthaben" | "Guthaben: 10.000,00 €", "Startkapital: …", "Zurückgesetzt: n-mal"; button "Guthaben zurücksetzen" opens a `ui.dialog` with the text "Guthaben auf <Startkapital> zurücksetzen? Punkte und Runden bleiben erhalten." and the buttons "Abbrechen" and "Zurücksetzen" |

Errors: set the text of the card's error label (`.classes("text-negative")`). Show nothing
else and change no data. Success: `ui.notify("Gespeichert")` and `render()`.

## 3. Tests

| File | Test | Asserts |
|---|---|---|
| `test_settings_rules.py` | name | `"  Anna  "` → `"Anna"`; `""`, `"   "`, 41 chars → message 1; `"anna"` with existing `["Anna"]` → message 2; 40 chars OK |
| | capital | 1000, 1000000, 10000.0 OK; 999, 1000001, 1500.5, None → error |
| | leverage | (5, 10), (2, 2), (20, 20) OK; (1, 10), (5, 21), (12, 10), (5.5, 10) → error |
| | rates | 0.0, 5.0, 20.0 → 0, 50, 200; 20.1, −0.1, 5.05, None → error; fee max 10.0 |
| | validate_settings | returns `UserSettings`; the first invalid field raises |
| `test_fmt.py` | `eur(Decimal("10000"))` = "10.000,00 €"; `eur(Decimal("-1247.14"))` = "-1.247,14 €"; `pct(0.016)` = "+1,60 %"; `pct(-0.124714)` = "-12,47 %"; `price(Decimal("97.85"))` = "97,85"; `date_de(date(2024, 12, 31))` = "31.12.2024"; `points(1240)` = "1.240"; `qty(Decimal(20))` = "≈ 20" | |
| `test_db.py` | init | fresh file → tables exist, `schema_version() == 1`; `init()` twice is fine |
| | create and read | defaults 5/10/50/20; balance = start capital; `active_user_id` = new id |
| | unique name | second `"ANNA"` → `sqlite3.IntegrityError` |
| | check B ≥ 0 | raw `UPDATE users SET balance_cents = -1` → `sqlite3.IntegrityError` |
| | settings don't touch balance | balance 5,000 € (raw UPDATE), change start capital to 20,000 → balance still 5,000 |
| | reset | balance 5,000 → `reset_balance` → balance = start capital; `resets` row with `balance_before_cents == 500000` and `at == now`; `reset_count == 1` |
| | active user survives restart | new `Database` on the same path → same `active_user_id` |
| `test_ui_setup.py` | create | fill "Name" and "Startkapital (€)", click "Anlegen" → the select's options contain the name; header shows the name |
| | invalid → message, no row | empty name → should_see message 1; `db.users() == []` |
| | settings error | "Hebel Mittel" 12, "Hebel Profi" 10, "Speichern" → message; DB unchanged |
| | settings saved | "Gebührensatz (%)" 2.5 → `fee_tenths == 25` |
| | reset needs confirmation | balance set to 5,000 € via raw SQL; click "Guthaben zurücksetzen", then "Abbrechen" → unchanged; again, then "Zurücksetzen" → 10,000 € and "Zurückgesetzt: 1-mal" |
| | preselected after restart | two users, the second active → open "/setup" → the select's value is the second id |
| `test_ui_shell.py` (extend) | no user → hint | open "/" without users → should_see "Noch kein Nutzer angelegt." |

Test tips: `user.find(ui.input).elements` and `user.find(ui.number).elements` are sets; find by
label with `user.find(marker=...)` after adding `.mark("name")` etc. to the elements (NiceGUI
`mark()`), then `user.find(marker="name").type("Anna")`. For numbers set the value directly:
`next(iter(user.find(marker="capital").elements)).set_value(999)`.

## 4. Steps

1. `settings_rules.py`, `fmt.py` (red → green).
2. `db.py` (red → green).
3. `PageContext`, root and header changes; keep the M2 UI tests green (the fixture now also creates a
   user where a test needs a chart).
4. `ui/setup.py` (red → green).
5. Gate, docs (`docs/architecture.md`: the SQLite tables).

## 5. Pitfalls

- `bind_text_from(ctx, "user_name")` needs a plain attribute on a normal object: that's why
  `PageContext` is a (non-frozen) dataclass.
- Case-insensitive uniqueness uses `casefold()`, which also handles `ß`/`SS`. The DB's `name_key`
  column mirrors it.
- Changing leverage or rates while a round is open (M6) needs no special code: the play page
  recomputes the cards from the DB whenever it renders.
- Never delete users (A16): no delete method in `Database`.
