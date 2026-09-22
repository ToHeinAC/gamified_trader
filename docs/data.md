# Ticker universe

`src/app/resources/universe.csv` (668 rows, columns `ticker,name,market`; 666 currently resolve on
Yahoo, see the manual check below), built once by a
throwaway script per [spec-m1-data.md §2.5](spec-m1-data.md#25-universepy-adapter-and-universecsv).
Reference date: 2026-09-22.

## Sources (English Wikipedia, current constituents)

| Market | Page | Rows |
|---|---|---|
| SP500 | `List_of_S%26P_500_companies` | 503 |
| NASDAQ100 | `List_of_NASDAQ-100_companies` (the `Nasdaq-100` page no longer lists constituents; the list lives on this separate page) | 101 in the source table, 15 kept |
| DAX | `DAX` | 40 |
| MDAX | `MDAX` | 47 |
| SDAX | see below | 63 |

## Conversions

- US tickers: `.` → `-` (`BRK.B` → `BRK-B`).
- German tickers: `.DE` appended unless the source already gives a Yahoo suffix (for example
  `AIR.PA` for Airbus, `PAH3.DE` for Porsche SE — both taken as-is from the DAX table).
- Strip whitespace, upper-case.
- Dedup by ticker, keeping the first market in `MARKETS` order
  (`SP500, NASDAQ100, DAX, MDAX, SDAX`). Most large NASDAQ-100 names are already S&P 500 members,
  which is why only 15 NASDAQ100-exclusive rows remain.

## SDAX: no ticker column on Wikipedia

Neither the English nor the German Wikipedia SDAX page lists ticker symbols (checked 2026-09-22:
both only have Name/Industry/Location-style columns). Resolved instead via `yfinance.Search`,
trying the plain company name, an ASCII-transliterated name (umlauts confuse the search), its
first word, and the name with "SE" appended, accepting the first hit quoted on a German exchange
and normalizing it to its Xetra symbol (`<base>.DE`).

`yfinance`'s search endpoint rate-limits after many rapid queries in one run and silently drops
results instead of erroring. 5 companies kept failing across repeated runs even though isolated
lookups resolved them; they turned out to already be in the universe as MDAX members with the same
ticker (Befesa, Evotec, Jenoptik, Siltronic, Stabilus — correctly deduped, since MDAX ranks above
SDAX). No manual override was needed in the end.

## Spot-checked German tickers

`ADS.DE` (Adidas), `AIR.PA` (Airbus), `SAP.DE`, `AIXA.DE` (Aixtron), `AT1.DE` (Aroundtown) — all
resolve on Yahoo with EUR prices individually. The conversion step's suffix rule
(`.DE` appended "unless the source already gives a Yahoo suffix") checked only for a `.DE` ending,
so `AIR.PA` (already suffixed for Euronext Paris) became `AIR.PA.DE` and failed to download. Fixed
by hand in the CSV to `AIR.PA`; the rule should check for any `.` instead of `.DE` specifically.

## Manual full download (2026-09-22)

`uv run gt data download` for the full universe: 666 of 668 succeeded (99.7 %), 5,263,922 rows,
42,614 corrections. Failed: `AIR.PA.DE` (the suffix bug above, fixed and re-downloaded
individually) and `ECV.DE` (Encavis — taken private and delisted from Xetra in 2024, "possibly
delisted" from Yahoo; expected, not a data-pipeline issue). `uv run gt data update` afterwards: 667
succeeded, 0 rows added (same trading day), 0 reloads.

## Data layout

`data/prices/<TICKER>.parquet`, columns `date, open, high, low, close, volume`
(`datetime64[ns]`, `float64` ×4, `int64`), one row per trading day, `auto_adjust=True` (splits and
dividends baked into the price). `gt data download` builds the full history per ticker;
`gt data update` appends new days and reloads a ticker's full history when Yahoo has re-adjusted
past prices (D13, see [spec-common.md](spec-common.md#1-decisions-beyond-the-prd)).
