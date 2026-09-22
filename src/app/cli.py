"""`gt` command-line entry point."""

import argparse
import os
import time
from collections.abc import Mapping, Sequence
from typing import cast

from app import data_sync, pool, pool_store, yahoo
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


def _render_pool_report(report: Mapping[str, object]) -> str:
    period = cast(list[str], report["period"])
    label_counts = cast(dict[str, dict[str, int]], report["label_counts"])
    without = cast(list[str], report["tickers_without_snapshots"])
    notes = cast(list[str], report["notes"])

    lines = [
        f"Snapshots: {report['n']} (seed {report['seed']})",
        f"Ticker: {report['n_tickers']}",
        f"Zeitraum: {period[0]} - {period[1]}",
        f"Signalanteil: {cast(float, report['signal_share']):.1%}",
    ]
    for level_key, counts in label_counts.items():
        lines.append(f"Labelverteilung {level_key}: {counts}")
    if without:
        lines.append(f"Ohne Snapshots: {len(without)} Ticker")
    lines.extend(notes)
    return "\n".join(lines)


def _snapshots_build(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = PriceStore(cfg.prices_dir)
    tickers = store.tickers()
    if not tickers:
        print("Keine Kursdaten gefunden. Zuerst `gt data download` ausführen.")
        return 1
    try:
        df, report = pool.build_pool(tickers, store.read, args.n, args.seed)
    except pool.InsufficientSnapshotsError as exc:
        print(str(exc))
        return 1
    pool_store.write_pool(df, report, cfg.snapshots_parquet, cfg.snapshots_json)
    print(_render_pool_report(report))
    return 0


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

    snapshots_parser = subparsers.add_parser("snapshots", help="Snapshot-Pool verwalten")
    snapshots_subparsers = snapshots_parser.add_subparsers(dest="snapshots_command", required=True)

    build_parser = snapshots_subparsers.add_parser("build", help="Pool erzeugen")
    build_parser.add_argument("--n", type=int, default=50_000)
    build_parser.add_argument("--seed", type=int, default=42)
    build_parser.set_defaults(func=_snapshots_build)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
