"""Read the ticker universe shipped as resources/universe.csv."""

import csv
import functools
import importlib.resources
import io
from dataclasses import dataclass

MARKETS = ("SP500", "NASDAQ100", "DAX", "MDAX", "SDAX")


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    name: str
    market: str


def load_universe() -> list[UniverseEntry]:
    path = importlib.resources.files("app") / "resources" / "universe.csv"
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [
        UniverseEntry(ticker=row["ticker"], name=row["name"], market=row["market"])
        for row in reader
    ]


@functools.lru_cache(maxsize=1)
def ticker_names() -> dict[str, str]:
    return {entry.ticker: entry.name for entry in load_universe()}
