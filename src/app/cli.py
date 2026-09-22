"""`gt` command-line entry point."""

import argparse
import os
import time
from collections.abc import Sequence

from app import data_sync, yahoo
from app.config import Config, load_config
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


def _cmd_app(cfg: Config) -> int:
    storage = cfg.data_dir / "nicegui"
    storage.mkdir(parents=True, exist_ok=True)  # NiceGUI's own mkdir has no parents=True
    os.environ.setdefault("NICEGUI_STORAGE_PATH", str(storage))
    from app.ui.root import run_app  # lazy: NiceGUI reads NICEGUI_STORAGE_PATH at import time

    run_app(cfg)
    return 0


def _app(_args: argparse.Namespace) -> int:
    return _cmd_app(load_config())


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

    app_parser = subparsers.add_parser("app", help="Web-App starten")
    app_parser.set_defaults(func=_app)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
