# Implementation spec M3: trade cards, simulation and scoring

PRD: §4 R3–R9, "Rechenbeispiel", M3. Common rules: [spec-common.md](spec-common.md) (D1–D3, D7).
Result: one pure module `src/app/trading.py` (no pandas, no I/O) and its tests. M4 and M6 only call
it and never re-implement a rule.

The Decimal approach below was checked against every number of the PRD worked example on
2026-09-21 (reference script, not in the repo). All values match exactly.

## 1. Design: `src/app/trading.py`

### 1.1 Types and constants

```python
class OptionCode(StrEnum):
    K10 = "K10"; K30 = "K30"; K120 = "K120"; W10 = "W10"; W30 = "W30"; W120 = "W120"

OPTIONS = (OptionCode.K10, OptionCode.K30, OptionCode.K120,
           OptionCode.W10, OptionCode.W30, OptionCode.W120)     # order = label tie-break (M4)
HORIZONS = (10, 30, 120)

class Level(StrEnum):
    EINFACH = "Einfach"; MITTEL = "Mittel"; PROFI = "Profi"

class ExitReason(StrEnum):
    TP = "TP"; SL = "SL"; KO = "KO"; TIME = "TIME"

K_FACTOR = {10: Decimal("1.5"), 30: Decimal("2.5"), 120: Decimal("4.0")}
RISK = Decimal("0.01")          # rho
MIN_D = Decimal("0.01")
MAX_D_SIMPLE = Decimal("0.30")
KO_BUFFER = Decimal("0.8")      # d_max(L > 1) = 0.8 / L
DAYS_PER_YEAR = 252
EPS = 0.0001
LOCK_SHARE = Decimal("0.01")    # R9
CENT = Decimal("0.01")
BP = Decimal("0.0001")

@dataclass(frozen=True)
class Costs:
    fee_rate: Decimal          # g, e.g. Decimal("0.02")
    interest_rate: Decimal     # z p.a., e.g. Decimal("0.05")

DEFAULT_COSTS = Costs(Decimal("0.02"), Decimal("0.05"))
```

Helpers: `dec(x: float) -> Decimal` (`Decimal(repr(x))`), `horizon_of(o) -> int`,
`is_buy(o) -> bool`, `buy_option(h) -> OptionCode`, `wait_option(h) -> OptionCode`,
`leverage_for(level, lev_mid, lev_pro) -> int` (Einfach → 1).

### 1.2 Card (R4, R5)

```python
def distance(horizon: int, atr: float, p0: float, leverage: int) -> Decimal:
    """clamp(k_H * A / P0, 1 %, d_max(L)), then quantize(BP, ROUND_HALF_UP) (D2)."""

def stake(d: Decimal, balance: Decimal) -> tuple[Decimal, Decimal]:
    """f = min(1, RISK / d); M = (f * balance) quantized to CENT with ROUND_FLOOR."""

def stop_levels(base: Decimal, d: Decimal, leverage: int) -> tuple[Decimal, Decimal, Decimal | None]:
    """SL = base*(1-d) ROUND_FLOOR to CENT; TP = base*(1+2d) ROUND_CEILING to CENT;
    KO = base*(1 - 1/L) unrounded (D3), None for L == 1."""

def fee(stake: Decimal, costs: Costs) -> Decimal:                         # g*M, HALF_UP to CENT
def financing(stake: Decimal, leverage: int, costs: Costs, days: int) -> Decimal:
    """(L-1)*M*z*days/252, HALF_UP to CENT; 0 for L == 1."""

@dataclass(frozen=True)
class Card:
    option: OptionCode            # K option only
    horizon: int
    leverage: int
    costs: Costs
    p0: Decimal
    d: Decimal
    f: Decimal
    stake: Decimal                # M
    exposure: Decimal             # X = M*L
    fee: Decimal                  # G
    sl_price: Decimal             # preview on P0
    tp_price: Decimal
    ko_price: Decimal | None
    qty: Decimal                  # X / P0, unrounded (UI rounds)
    financing_full: Decimal       # F with days = H
    ko_distance: Decimal | None   # -1/L as a fraction (UI shows -100/L %)
    loss_at_sl: Decimal           # M*L*d + G, HALF_UP to CENT
    gain_at_tp: Decimal           # M*L*2d - G, HALF_UP to CENT

def make_card(horizon: int, p0: float, atr: float, balance: Decimal,
              leverage: int, costs: Costs) -> Card:
def make_cards(p0: float, atr: float, balance: Decimal, leverage: int,
               costs: Costs) -> dict[OptionCode, Card]:          # keys K10, K30, K120
```

The card is fixed before trading starts. The simulation reuses `card.d`, `card.stake` and
`card.fee` unchanged, even when the entry E differs from P0 (PRD M3 edge case: f stays the card's value).

### 1.3 Simulation (R6)

```python
@dataclass(frozen=True)
class TradeResult:
    entry: Decimal
    sl: Decimal
    tp: Decimal
    ko: Decimal | None
    exit_price: Decimal
    reason: ExitReason
    exit_day: int                 # n, 1..H
    ret: Decimal                  # exit/E - 1
    fee: Decimal
    financing: Decimal
    pnl: Decimal                  # max(-M, M*L*r - G - F), HALF_UP to CENT

def exit_on_day(day: int, o: Decimal, h: Decimal, l: Decimal, sl: Decimal, tp: Decimal,
                ko: Decimal | None) -> tuple[Decimal, ExitReason] | None:
    """R6 rows 1-5 in order; rows 1-3 only for day >= 2."""

def simulate(card: Card, future: Sequence[Sequence[float]]) -> TradeResult:
    """future[i] = (open, high, low, close) of day i+1 after Tag 0."""

def simulate_all(cards: Mapping[OptionCode, Card],
                 future: Sequence[Sequence[float]]) -> dict[int, TradeResult]:   # key = horizon
```

- `len(future) < card.horizon` → `ValueError(f"benötigt {H} Kerzen nach Tag 0, vorhanden {n}")`.
- E = `dec(future[0][0])`; `sl, tp, ko = stop_levels(E, card.d, card.leverage)`.
- Convert only the current day's bar to Decimal, inside the loop (performance, see M4).
- Without an exit: exit price `dec(close of day H)`, reason TIME, n = H.
- Rounding of the P&L: compute `M*L*r - G - F` unrounded, apply `max(-M, ·)`, then quantize.

### 1.4 Values, points, booking (R7–R9)

```python
def option_values(results: Mapping[int, TradeResult], balance: Decimal) -> dict[OptionCode, float]:
    """V(K_H) = float(pnl / balance); V(W_H) = -V(K_H). ValueError if balance <= 0."""
def is_neutral(values: Mapping[OptionCode, float]) -> bool            # max(V) < EPS
def optimal_options(values) -> list[OptionCode]                       # V >= V* - EPS, OPTIONS order; [] if neutral
def points(values) -> dict[OptionCode, int]
    # neutral -> all 0; optimal -> 100; V > 0 -> min(99, floor(100*V/V* + 1e-9)); else 0
def label(values) -> str                                              # first optimal code, or "NEUTRAL"
def book(balance: Decimal, option: OptionCode, pnl: Decimal) -> Decimal   # K: B + pnl, W: B
def k_locked(balance: Decimal, start_capital: Decimal) -> bool           # B < 1 % of start capital
def value_balance(balance: Decimal, start_capital: Decimal) -> Decimal   # D7: start capital if locked
```

## 2. Tests

Shared fixture for the worked example: B = `Decimal("10000.00")`, P0 = 100.0, A = 2.0,
`DEFAULT_COSTS`. A "quiet" bar `Q = (100.0, 100.5, 99.5, 100.0)` triggers nothing for K30
(SL 95, TP 110, KO 90). `future(*bars)` pads with Q to 30 or 120 days.

**`test_trading_card.py`**

| Test | Asserts |
|---|---|
| example table | K10: d 0.0300, SL 97.00, TP 106.00, f = 1/3 (as Decimal division), M 3333.33, G 66.67; K30: 0.0500, 95.00, 110.00, 0.2, 2000.00, 40.00; K120: 0.0800, 92.00, 116.00, 0.125, 1250.00, 25.00 |
| card K30 Einfach | X 2000.00, qty 20, loss_at_sl 140.00, gain_at_tp 160.00, financing_full 0, ko_price None |
| card K30 Profi (L = 10) | X 20000.00, qty 200, loss_at_sl 1040.00, gain_at_tp 1960.00, financing_full 107.14, ko_distance −0.1 |
| K120 Profi clamp edge | d == 0.0800 (raw = d_max) |
| gap entry E = 103 | `stop_levels(Decimal("103.00"), Decimal("0.05"), 1)` → SL 97.85, TP 113.30 (the float version floors to 97.84); simulate with day 1 open 103 → `card.stake` still 2000.00 |
| clamp low | A = 0.01 → d = 0.0100 and f = 1, M = B |
| clamp high | A = 10, H = 30, L = 10 → d = 0.0800; tp_price = 116.00 (follows the clamped d) |
| fee on all levels | G identical for L = 1, 5, 10 |
| leverage_for | Einfach 1, Mittel lev_mid, Profi lev_pro |

**`test_trading_sim.py`** (K30, E = 100 unless noted)

| Test | Bars | Expect |
|---|---|---|
| TP day 2 | Q, (99, 111, 98, 100) | TP, exit 110.00, n 2, P&L 160.00; V +0.016; `book` → 10160.00 |
| SL day 1, no gap rule on day 1 | (100, 100, 94, 95) | SL, exit 95.00 (not 94), n 1, V −0.014 |
| TP day 1 intraday | (100, 111, 99, 105) | TP 110.00, n 1 |
| gap SL day 2 | Q, (94, 94, 94, 94) | SL, exit 94.00, P&L −160.00, V −0.016 |
| gap SL day 2 Profi | same, L = 10 | F 7.14, P&L −1247.14, V −0.124714 |
| gap under KO before SL | Q, (89, 89, 89, 89), L = 10 | KO, P&L −2000.00 (= −M), V −0.2 |
| gap TP day 2 | Q, (112, 113, 111, 112) | TP, exit 112.00 (open, not 110) |
| SL before TP same day | Q, (100, 111, 94, 100) | SL 95.00, V −0.014 |
| time exit | 29 × Q, then (100, 103.5, 99.5, 103) | TIME, n 30, exit 103.00, P&L 20.00, V +0.002 |
| SL equal to KO | `exit_on_day(2, o=Decimal(89), …, sl=Decimal(90), ko=Decimal(90))` | KO (row 1 wins) |
| too few bars | 29 bars for H = 30 | `ValueError` |
| no costs | g = z = 0, TP day 2 | P&L 200.00 |
| F = 0 at L = 1; F linear in n | `financing(2000, 10, DEFAULT_COSTS, n)` for n = 1..30 equals `(9*2000*0.05*n/252)` rounded; F(20) − 2·F(10) within ±0.01 |
| loss floor | L = 20, day 2 open 1.0 | P&L == −M |

**`test_trading_points.py`**

| Test | Asserts |
|---|---|
| example points | V = {K10 0.012, K30 −0.010, K120 0.020} (+ mirrored W) → K120 100, K10 60, W30 50, rest 0 |
| multiple optima | two options with V* and V* − 0.00005 → both 100 |
| neutral | all \|V\| < EPS → all 0; `label` == "NEUTRAL"; `optimal_options` == [] |
| label tie-break | K30 and W10 both optimal → "K30" |
| cap 99 | V = V* − 0.0002 (> EPS below) → 99 |
| booking | W option → balance unchanged; K → B + pnl |
| lock | `k_locked(0, 10000)` True; 99.99 True; 100.00 False; `value_balance(0, 10000) == 10000` |
| option_values on B = 0 | `ValueError` |

**`test_trading_properties.py`** (D12: seeded loops, 50 seeds, well under 5 s)

Per seed: L ∈ {1, 5, 10, 20}; A ∈ [0.1, 15]; P0 ∈ [5, 500]; B ∈ [100, 1e6] (Decimal, 2 places);
120 future bars from a random walk around P0 with random gaps (open = previous close ·
exp(normal(0, 0.03))), valid OHLC. Assert for every H: P&L ≥ −M; `book(B, K, pnl) ≥ 0`; for the
values, V(W_H) == −V(K_H) exactly; if not neutral, `{o: points == 100}` == `{o: V ≥ V* − EPS}`;
all points in [0, 100].

## 3. Steps

1. Types, constants, helpers, `distance`, `stake`, `stop_levels`, `fee`, `financing`, `Card`,
   `make_card(s)`: tests first (card file).
2. `exit_on_day`, `simulate`, `simulate_all`: tests first (sim file).
3. `option_values`, `points`, `label`, `book`, `k_locked`, `value_balance`: tests first (points file).
4. Property tests, then gate and docs. There are no manual checks in M3.

## 4. Pitfalls

- `Decimal(0.03)` ≠ `Decimal("0.03")`. Only `dec()` converts floats.
- `exit_on_day` with 5 rows plus a day guard is close to the complexity limit of 10. Group rows 1–3
  in a helper `_gap_exit(o, sl, tp, ko)` if ruff complains.
- Keep `trading.py` free of pandas; callers pass lists of float tuples.
- Card fields are Decimal. Formatting belongs to `fmt.py` (M5), not here.
