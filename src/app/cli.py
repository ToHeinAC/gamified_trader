"""`gt` command-line entry point."""

import argparse
import time
from collections.abc import Sequence

from app import data_sync, yahoo
from app.config import load_config
from app.price_store import PriceStore
from app.universe import load_universe


def _tickers_or_universe(tickers: Sequence[str] | None) -> list[str]:
    if tickers:
        return list(tickers)
    return [entry.ticker for entry in load_universe()]


def _data_download(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = PriceStore(cfg.prices_dir)
    report = data_sync.download(
        _tickers_or_universe(args.tickers),
        store,
        fetch=yahoo.fetch_batch,
        sleep=time.sleep,
        pause_s=cfg.yahoo_pause_s,
    )
    print(report.render())
    return report.exit_code()


def _data_update(_args: argparse.Namespace) -> int:
    cfg = load_config()
    store = PriceStore(cfg.prices_dir)
    report = data_sync.update(
        store,
        fetch=yahoo.fetch_batch,
        sleep=time.sleep,
        pause_s=cfg.yahoo_pause_s,
    )
    print(report.render())
    return report.exit_code()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    data_parser = subparsers.add_parser("data", help="Kursdaten verwalten")
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)

    download_parser = data_subparsers.add_parser("download", help="Historie herunterladen")
    download_parser.add_argument("--tickers", nargs="+", default=None)
    download_parser.set_defaults(func=_data_download)

    update_parser = data_subparsers.add_parser("update", help="Neue Tage nachladen")
    update_parser.set_defaults(func=_data_update)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
