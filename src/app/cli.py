"""`gt` command-line entry point."""

import argparse
import os
import time
from collections.abc import Mapping, Sequence
from typing import cast

from app import data_sync, market, ml, model_store, pool, pool_store, yahoo
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


def _growth_lines(metadata: Mapping[str, object]) -> list[str]:
    baselines = cast(dict[str, float], metadata["growth_baselines"])
    beats = cast(dict[str, bool], metadata["beats_baselines"])
    folds = cast(list[dict[str, float]], metadata["fold_growth"])
    worst = cast(dict[str, float], metadata["worst_fold_growth"])
    lines = [f"Wachstum Modell: {cast(float, metadata['growth_model']):+.3%} je Runde"]
    for name, value in baselines.items():
        yes = "ja" if beats[name] else "nein"
        lines.append(f"Wachstum Baseline {name}: {value:+.3%} (geschlagen: {yes})")
    lines.append("Wachstum je Fold: " + ", ".join(f"{f['model']:+.3%}" for f in folds))
    lines.append(
        f"Schlechtester Fold: Modell {worst['model']:+.3%}, "
        + ", ".join(f"{name} {worst[name]:+.3%}" for name in baselines)
    )
    positive = "ja" if metadata["all_folds_positive"] else "nein"
    lines.append(f"Alle Folds positiv: {positive}")
    lines.append(f"Gehandelt: {cast(float, metadata['traded_share']):.0%} der Runden")
    lines.append(f"5-%-Quantil gebucht: {cast(float, metadata['booked_p5']):+.2%} von B")
    return lines


def _render_model_report(metadata: Mapping[str, object]) -> str:
    period = cast(list[str], metadata["period"])
    coverage = cast(dict[str, dict[str, float]], metadata["quantile_coverage"])
    importance = cast(dict[str, float], metadata["importance"])

    lines = [
        f"Snapshots: {metadata['n_snapshots']} (seed {metadata['seed']})",
        f"Zeitraum: {period[0]} - {period[1]}",
        *_growth_lines(metadata),
        f"Spiel-Sicht: Ø V {cast(float, metadata['mean_v_model']):+.4f}, "
        f"Ø Punkte {cast(float, metadata['mean_points']):.1f}",
    ]
    for key, stats in coverage.items():
        lines.append(f"Abdeckung {key}: P25={stats['p25']:.2f} P75={stats['p75']:.2f}")
    lines.append("Top-10 Feature Importance:")
    for feature, score in list(importance.items())[:10]:
        lines.append(f"  {feature}: {score:.5f}")
    return "\n".join(lines)


def _model_train(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg.snapshots_parquet.exists():
        print("Kein Pool gefunden. Zuerst `gt snapshots build` ausführen.")
        return 1
    store = PriceStore(cfg.prices_dir)
    pool_df = pool_store.read_pool(cfg.snapshots_parquet)
    mkt = market.market_frame(store.tickers(), store.read)
    model_store.write_market(mkt, cfg.market_parquet)
    result = ml.train(pool_df, store.read, mkt, args.seed)
    model_store.write_features(result.features, cfg.features_parquet)
    model_store.write_model(result.models, result.metadata, cfg.model_path, cfg.model_meta_path)
    print(_render_model_report(result.metadata))
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

    model_parser = subparsers.add_parser("model", help="ML-Modell verwalten")
    model_subparsers = model_parser.add_subparsers(dest="model_command", required=True)

    train_parser = model_subparsers.add_parser("train", help="Modell trainieren")
    train_parser.add_argument("--seed", type=int, default=42)
    train_parser.set_defaults(func=_model_train)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
