"""Pure rules for Entdeckungsmodus (PRD M8): ticker input, cache freshness, analysis.

No I/O; no sklearn import (the bundle's models only need `.predict`).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import cast

import pandas as pd

from app import universe
from app.db import UserRow
from app.discover_store import MetaEntry
from app.features import FEATURE_COLUMNS, compute_features, with_market
from app.game import Setting, setting_for
from app.ml import QuantileModel, Recommendation, predict_quantiles, recommend
from app.settings_rules import FEE_DEFAULT_TENTHS, INTEREST_DEFAULT_TENTHS, LEV_MID_DEFAULT
from app.signals import signal_flags
from app.trading import Card, horizon_of, is_buy, k_locked, make_card
from app.universe import UniverseEntry

TICKER_RE = re.compile(r"^[A-Z0-9.\-^=]{1,20}$")
MIN_BARS = 250
DEFAULT_LEV_MID = LEV_MID_DEFAULT
DEFAULT_FEE_TENTHS, DEFAULT_INTEREST_TENTHS = FEE_DEFAULT_TENTHS, INTEREST_DEFAULT_TENTHS
TOP_FEATURES = 5
SUGGESTION_SEP = " · "
MARKET_STALE_DAYS = 5


class Status(StrEnum):
    OK = "ok"
    TOO_SHORT = "too_short"
    NOT_EQUITY = "not_equity"
    NO_MODEL = "no_model"
    MODEL_MISMATCH = "model_mismatch"
    MARKET_STALE = "market_stale"


@dataclass(frozen=True)
class ModelBundle:
    models: Mapping[tuple[int, int, float], QuantileModel]
    meta: Mapping[str, object]


@dataclass(frozen=True)
class FeatureInfo:
    name: str
    value: float | None
    percentile: float | None


@dataclass(frozen=True)
class Analysis:
    ticker: str
    ind: pd.DataFrame
    status: Status
    recommendation: Recommendation | None
    quantiles: dict[tuple[int, int], tuple[float, float, float]]
    top_features: list[FeatureInfo]
    beats_all: bool | None


def suggestions(entries: Sequence[UniverseEntry]) -> list[str]:
    return [f"{entry.ticker}{SUGGESTION_SEP}{entry.name}" for entry in entries]


def normalize_ticker(text: str) -> str | None:
    candidate = text.split(SUGGESTION_SEP, 1)[0].strip().upper()
    if not TICKER_RE.fullmatch(candidate):
        return None
    if set(candidate) <= {"."}:
        return None
    return candidate


def display_name(ticker: str) -> str:
    return universe.ticker_names().get(ticker, ticker)


def needs_fetch(entry: MetaEntry | None, today: date) -> bool:
    return entry is None or entry.fetched < today


def completed_bars(bars: pd.DataFrame, today: date) -> pd.DataFrame:
    cutoff = pd.Timestamp(today)
    return bars.loc[bars["date"] < cutoff].reset_index(drop=True)


def beats_all(meta: Mapping[str, object]) -> bool:
    return all(cast(Mapping[str, bool], meta["beats_baselines"]).values())


def model_matches(meta: Mapping[str, object]) -> bool:
    return list(cast(Sequence[str], meta["feature_columns"])) == list(FEATURE_COLUMNS)


def needs_model_hint(user: UserRow) -> bool:
    return (
        user.lev_mid != DEFAULT_LEV_MID
        or user.fee_tenths != DEFAULT_FEE_TENTHS
        or user.interest_tenths != DEFAULT_INTEREST_TENTHS
    )


def market_fresh(market: pd.DataFrame | None, tag0: pd.Timestamp) -> bool:
    if market is None or market.empty:
        return False
    return bool(tag0 - market.index.max() <= pd.Timedelta(days=MARKET_STALE_DAYS))


def feature_row(ind: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    stock = compute_features(ind, signal_flags(ind)).iloc[[-1]]
    dates = pd.Series([ind["date"].iloc[-1]])
    return with_market(stock, dates, market)


def quantiles_for(
    models: Mapping[tuple[int, int, float], QuantileModel], row: pd.DataFrame
) -> dict[tuple[int, int], tuple[float, float, float]]:
    preds = predict_quantiles(models, row)
    return {lh: (float(a[0][0]), float(a[1][0]), float(a[2][0])) for lh, a in preds.items()}


def _percentile(value: float, pool_column: pd.Series) -> float | None:
    column = pool_column.dropna()
    if column.empty:
        return None
    return float((column <= value).mean())


def top_features(
    meta: Mapping[str, object], row: pd.DataFrame, pool_features: pd.DataFrame | None
) -> list[FeatureInfo]:
    importance = cast(Mapping[str, float], meta["importance"])
    out: list[FeatureInfo] = []
    for name in list(importance)[:TOP_FEATURES]:
        raw = row[name].iloc[0]
        value = None if pd.isna(raw) else float(raw)
        percentile = None
        if value is not None and pool_features is not None and name in pool_features.columns:
            percentile = _percentile(value, pool_features[name])
        out.append(FeatureInfo(name=name, value=value, percentile=percentile))
    return out


def _empty_analysis(ticker: str, ind: pd.DataFrame, status: Status) -> Analysis:
    return Analysis(
        ticker=ticker,
        ind=ind,
        status=status,
        recommendation=None,
        quantiles={},
        top_features=[],
        beats_all=None,
    )


def analyze(
    ticker: str,
    ind: pd.DataFrame,
    quote_type: str | None,
    bundle: ModelBundle | None,
    market: pd.DataFrame | None,
    pool_features: pd.DataFrame | None,
) -> Analysis:
    """R13 recommendation for the last completed bar; `ind` never includes today's bar."""
    if len(ind) < MIN_BARS:
        return _empty_analysis(ticker, ind, Status.TOO_SHORT)
    if quote_type != "EQUITY":
        return _empty_analysis(ticker, ind, Status.NOT_EQUITY)
    if bundle is None:
        return _empty_analysis(ticker, ind, Status.NO_MODEL)
    if not model_matches(bundle.meta):
        return _empty_analysis(ticker, ind, Status.MODEL_MISMATCH)
    tag0 = pd.Timestamp(ind["date"].iloc[-1])
    if not market_fresh(market, tag0):
        return _empty_analysis(ticker, ind, Status.MARKET_STALE)

    assert market is not None
    row = feature_row(ind, market)
    quantiles = quantiles_for(bundle.models, row)
    rec = recommend(quantiles)
    feats = top_features(bundle.meta, row, pool_features)
    return Analysis(
        ticker=ticker,
        ind=ind,
        status=Status.OK,
        recommendation=rec,
        quantiles=quantiles,
        top_features=feats,
        beats_all=beats_all(bundle.meta),
    )


def recommendation_card(
    rec: Recommendation, ind: pd.DataFrame, user: UserRow | None
) -> tuple[Card, Setting] | None:
    if not is_buy(rec.option) or user is None:
        return None
    setting = setting_for(user, rec.level)
    if k_locked(setting.balance, setting.start_capital):
        return None
    atr = float(ind["atr14"].iloc[-1])
    if pd.isna(atr) or atr <= 0:
        return None
    p0 = float(ind["close"].iloc[-1])
    card = make_card(
        horizon_of(rec.option), p0, atr, setting.balance, setting.leverage, setting.costs
    )
    return card, setting
