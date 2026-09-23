"""Page "Entdecken": load any ticker, show a dated chart and the R13 recommendation (PRD M8)."""

from collections.abc import Mapping
from typing import cast

from nicegui import run, ui

from app import discover_service
from app.chart import Figure, build_discover_figure, discover_window
from app.discover import (
    Analysis,
    Status,
    display_name,
    needs_model_hint,
    normalize_ticker,
    recommendation_card,
    suggestions,
)
from app.discover_service import DiscoverError, DiscoverService, Loaded
from app.fmt import date_de, pct
from app.game import card_lines, setting_for, wait_lines
from app.ml import LEVEL_OF, growth_score
from app.theme import Theme
from app.trading import horizon_of, is_buy, k_locked
from app.ui.chart_panel import chart_panel
from app.ui.context import PageContext
from app.universe import load_universe

DISCLAIMER_TEXT = "Lern-App, keine Anlageberatung."
INVALID_TICKER_TEXT = "Ungültiges Tickersymbol."
BASELINE_HINT_TEXT = "Das Modell schlägt nicht jede einfache Vergleichsstrategie."
A22_HINT_TEXT = "Modell mit Hebel 1/5 und Standardkosten trainiert, die Karte nutzt Ihre Werte."
NO_USER_TEXT = "Positionsgröße: zuerst im Setup einen Nutzer anlegen."
LOCKED_TEXT = "Guthaben unter 1 % des Startkapitals \u2013 Reset im Setup."
ATR_ZERO_TEXT = "Keine Positionsgrößen-Berechnung möglich (ATR = 0)."

_STATUS_HINTS: dict[Status, str] = {
    Status.TOO_SHORT: "Weniger als 250 Kerzen \u2013 keine Empfehlung.",
    Status.NOT_EQUITY: "Modell nur auf Aktien trainiert \u2013 keine Empfehlung.",
    Status.NO_MODEL: "Kein Modell gefunden. Zuerst `gt model train` ausführen.",
    Status.MODEL_MISMATCH: (
        "Modell passt nicht zur Featureliste. `gt model train` erneut ausführen."
    ),
    Status.MARKET_STALE: "Marktdaten veraltet \u2013 `gt data update` ausführen.",
}


class DiscoverPage:
    def __init__(self, ctx: PageContext) -> None:
        self.ctx = ctx
        self.service = DiscoverService(ctx.cfg)
        with ui.element("div").classes("gt-card").mark("disclaimer"):
            ui.label(DISCLAIMER_TEXT)
        with ui.row().classes("items-end gap-2"):
            self.ticker_input = ui.input("Ticker", autocomplete=suggestions(load_universe())).mark(
                "ticker-input"
            )
            self.ticker_input.on("keydown.enter", lambda _e: self._on_load())
            self.load_button = ui.button("Laden", on_click=self._on_load).mark("load")
        self.result_container = ui.column().classes("w-full gap-4")

    async def _on_load(self) -> None:
        ticker = normalize_ticker(self.ticker_input.value or "")
        self.result_container.clear()
        if ticker is None:
            with self.result_container:
                ui.label(INVALID_TICKER_TEXT).mark("hint")
            return

        self.load_button.disable()
        with self.result_container:
            ui.spinner(size="lg")
        try:
            result = await run.io_bound(self.service.analyze, ticker)
        except DiscoverError as exc:
            self.result_container.clear()
            with self.result_container:
                ui.label(str(exc)).mark("hint")
            return
        finally:
            self.load_button.enable()
        if result is None:
            return  # cancelled or app shutting down (nicegui.run.io_bound)
        loaded, analysis = result

        self.result_container.clear()
        with self.result_container:
            self._render_result(ticker, loaded, analysis)

    def _render_result(self, ticker: str, loaded: Loaded, analysis: Analysis) -> None:
        if loaded.stale:
            text = f"Aktualisierung fehlgeschlagen \u2013 Datenstand {date_de(loaded.data_as_of)}."
            ui.label(text).mark("hint")
        name = display_name(ticker)
        with (
            ui.element("div")
            .classes("w-full flex flex-col lg:flex-row lg:flex-nowrap lg:gap-6")
            .mark("discover-layout")
        ):
            with ui.element("div").classes("lg:w-[64%] flex flex-col gap-4"):
                self._chart_pane(ticker, name, analysis)
            with ui.element("div").classes("lg:w-[36%] flex flex-col gap-4").mark("recommendation"):
                self._recommendation_pane(analysis)

    def _chart_pane(self, ticker: str, name: str, analysis: Analysis) -> None:
        ui.label(f"{ticker} · {name}, Datenstand {date_de(analysis.ind['date'].iloc[-1])}")
        window = discover_window(analysis.ind)

        def make_figure(theme: Theme) -> Figure:
            return build_discover_figure(window, theme, ticker, name)

        chart_panel(self.ctx, window, make_figure, presets=True)

    def _recommendation_pane(self, analysis: Analysis) -> None:
        if analysis.status != Status.OK:
            ui.label(_STATUS_HINTS[analysis.status]).mark("hint")
            return
        rec = analysis.recommendation
        assert rec is not None
        with ui.card().classes("gt-card"):
            if is_buy(rec.option):
                ui.label(f"{rec.option.value} · {rec.level.value}")
            else:
                ui.label(f"Warten {horizon_of(rec.option)} Tage")
            ui.label(
                f"Wachstum G {pct(rec.growth)} · P25 {pct(rec.p25)} · "
                f"P50 {pct(rec.p50)} · P75 {pct(rec.p75)}"
            )
            self._card_lines(analysis)

        user = self.ctx.active_user()
        if analysis.beats_all is False:
            self._baseline_hint()
        if user is not None and needs_model_hint(user):
            ui.label(A22_HINT_TEXT).mark("hint")
        self._quantile_table(analysis)
        self._top_features_table(analysis)

    def _card_lines(self, analysis: Analysis) -> None:
        rec = analysis.recommendation
        assert rec is not None
        if not is_buy(rec.option):
            for line in wait_lines(horizon_of(rec.option)):
                ui.label(line)
            return

        user = self.ctx.active_user()
        if user is None:
            ui.label(NO_USER_TEXT).mark("hint")
            ui.link("Zum Setup", "/setup")
            return
        setting = setting_for(user, rec.level)
        if k_locked(setting.balance, setting.start_capital):
            ui.label(LOCKED_TEXT).mark("hint")
            ui.link("Zum Setup", "/setup")
            return

        result = recommendation_card(rec, analysis.ind, user)
        if result is None:
            ui.label(ATR_ZERO_TEXT).mark("hint")
            return
        card, card_setting = result
        for line in card_lines(card, card_setting):
            ui.label(line)

    def _baseline_hint(self) -> None:
        bundle = discover_service.load_bundle(self.ctx.cfg)
        with ui.column().mark("hint"):
            ui.label(BASELINE_HINT_TEXT)
            if bundle is not None:
                growth_model = cast(float, bundle.meta["growth_model"])
                baselines = cast(Mapping[str, float], bundle.meta["growth_baselines"])
                ui.label(f"Wachstum Modell: {pct(growth_model)} je Runde")
                for name, value in baselines.items():
                    ui.label(f"Wachstum {name}: {pct(value)} je Runde")

    def _quantile_table(self, analysis: Analysis) -> None:
        columns = [
            {"name": n, "label": label, "field": n}
            for n, label in (
                ("pair", "Hebel/Horizont"),
                ("g", "G"),
                ("p25", "P25"),
                ("p50", "P50"),
                ("p75", "P75"),
            )
        ]
        rows = [
            {
                "pair": f"{LEVEL_OF[lev].value} · {h} Tage",
                "g": pct(growth_score(q)),
                "p25": pct(q[0]),
                "p50": pct(q[1]),
                "p75": pct(q[2]),
            }
            for (lev, h), q in analysis.quantiles.items()
        ]
        with ui.element("div").mark("quantile-table"):
            ui.table(columns=columns, rows=rows, row_key="pair")

    def _top_features_table(self, analysis: Analysis) -> None:
        columns = [
            {"name": n, "label": label, "field": n}
            for n, label in (("name", "Feature"), ("value", "Wert"), ("percentile", "Perzentil"))
        ]
        rows = [
            {
                "name": f.name,
                "value": f"{f.value:.4f}" if f.value is not None else "\u2013",
                "percentile": pct(f.percentile, signed=False)
                if f.percentile is not None
                else "\u2013",
            }
            for f in analysis.top_features
        ]
        with ui.element("div").mark("top-features"):
            ui.label("Top-5 Features")
            ui.table(columns=columns, rows=rows, row_key="name")


def discover_page(ctx: PageContext) -> None:
    DiscoverPage(ctx)
