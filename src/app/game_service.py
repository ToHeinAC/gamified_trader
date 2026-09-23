"""Round orchestration: wires the database, snapshot pool and price data (PRD M6)."""

import functools
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd

from app import discover, discover_service, universe
from app.config import Config
from app.db import Database, RoundRow, UserRow
from app.game import (
    PoolEntry,
    Resolution,
    SnapshotBars,
    draw_snapshot,
    outcome,
    resolve,
    setting_for,
    setting_of_round,
)
from app.indicators import with_indicators
from app.price_store import PriceStore
from app.trading import Level, OptionCode

logger = logging.getLogger(__name__)

_FUTURE_BARS = 120


class PoolMissingError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@functools.lru_cache(maxsize=4)
def _load_pool_entries(path_str: str, _mtime_ns: int) -> list[PoolEntry]:
    df = pd.read_parquet(path_str, columns=["snapshot_id", "ticker", "t0", "label_l1"])
    snapshot_ids: list[str] = df["snapshot_id"].tolist()
    tickers: list[str] = df["ticker"].tolist()
    t0s: list[pd.Timestamp] = df["t0"].tolist()
    labels: list[str] = df["label_l1"].tolist()
    return [
        PoolEntry(snapshot_id=sid, ticker=ticker, t0=t0.date(), label=label)
        for sid, ticker, t0, label in zip(snapshot_ids, tickers, t0s, labels, strict=True)
    ]


@dataclass(frozen=True)
class RoundData:
    ind: pd.DataFrame
    t0_idx: int
    snap: SnapshotBars


class GameService:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        rng: random.Random | None = None,
        now: Callable[[], str] = utc_now,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.rng = rng if rng is not None else random.Random()
        self.now = now

    def pool_entries(self) -> list[PoolEntry]:
        path = self.cfg.snapshots_parquet
        if not path.exists():
            raise PoolMissingError(str(path))
        return _load_pool_entries(str(path), path.stat().st_mtime_ns)

    def current(self, user_id: int) -> RoundRow | None:
        return self.db.open_round(user_id) or self.db.last_round(user_id)

    def start_round(self, user_id: int) -> RoundRow:
        entries = self.pool_entries()
        play_counts = self.db.play_counts(user_id)
        exclude: set[str] = set()
        while True:
            entry = draw_snapshot(entries, play_counts, self.rng, exclude=exclude)
            if entry is None:
                raise PoolMissingError("Kein Snapshot mehr verfügbar")
            try:
                self.load(entry.ticker, entry.t0)
            except (FileNotFoundError, KeyError):
                logger.warning("Snapshot %s übersprungen: Kursdatei fehlt", entry.snapshot_id)
                exclude.add(entry.snapshot_id)
                continue
            return self.db.insert_open_round(
                user_id, entry.snapshot_id, entry.ticker, entry.t0, self.now()
            )

    def load(self, ticker: str, t0: date) -> RoundData:
        bars = PriceStore(self.cfg.prices_dir).read(ticker)
        ind = with_indicators(bars)
        matches = ind.index[ind["date"] == pd.Timestamp(t0)]
        if len(matches) == 0:
            raise KeyError(f"t0 {t0} not found for {ticker}")
        t0_idx = int(matches[0])
        future = (
            ind[["open", "high", "low", "close"]]
            .iloc[t0_idx + 1 : t0_idx + 1 + _FUTURE_BARS]
            .to_numpy()
            .tolist()
        )
        snap = SnapshotBars(
            p0=float(ind["close"].iloc[t0_idx]),
            atr=float(ind["atr14"].iloc[t0_idx]),
            future=future,
        )
        return RoundData(ind=ind, t0_idx=t0_idx, snap=snap)

    def confirm(self, user: UserRow, rnd: RoundRow, level: Level, option: OptionCode) -> bool:
        data = self.load(rnd.ticker, rnd.t0)
        setting = setting_for(user, level)

        def _compute_outcome(before_cents: int):
            s = replace(setting, balance=Decimal(before_cents) / 100)
            res = resolve(data.snap, s, option)
            return outcome(res, user.fee_tenths, user.interest_tenths)

        return self.db.confirm_round(rnd.id, user.id, _compute_outcome, self.now())

    def resolution(self, rnd: RoundRow, user: UserRow) -> Resolution:
        data = self.load(rnd.ticker, rnd.t0)
        setting = setting_of_round(rnd, user.start_capital_cents)
        assert rnd.option is not None
        return resolve(data.snap, setting, OptionCode(rnd.option))

    def ml_quantiles(
        self, data: RoundData
    ) -> dict[tuple[int, int], tuple[float, float, float]] | None:
        """Model quantiles per (L, H) from the features at Tag 0; None without a usable model."""
        bundle = discover_service.load_bundle(self.cfg)
        market = discover_service.load_market(self.cfg)
        hist = data.ind.iloc[: data.t0_idx + 1]
        tag0 = pd.Timestamp(hist["date"].iloc[-1])
        if bundle is None or not discover.model_matches(bundle.meta):
            return None
        if market is None or not discover.market_fresh(market.loc[:tag0], tag0):
            return None
        return discover.quantiles_for(bundle.models, discover.feature_row(hist, market))

    def name_of(self, ticker: str) -> str:
        return universe.ticker_names().get(ticker, ticker)
