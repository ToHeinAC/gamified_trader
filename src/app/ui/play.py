"""Page "Spielen": draw -> decision -> confirmation -> resolution -> next round (PRD M6)."""

import pandas as pd
from nicegui import ui
from nicegui.events import ValueChangeEventArguments

from app.chart import (
    EXIT_LABELS,
    Figure,
    add_preview,
    build_figure,
    build_resolution_figure,
    decision_window,
    resolution_window,
)
from app.db import RoundRow, Stats, UserRow
from app.fmt import cents_eur, date_de, pct
from app.fmt import points as fmt_points
from app.game import (
    Card,
    Resolution,
    Setting,
    card_lines,
    decision_cards,
    round_number,
    setting_for,
    wait_lines,
)
from app.game_service import GameService, PoolMissingError, RoundData
from app.signals import EVENT_LABELS, signal_flags
from app.theme import Theme
from app.trading import HORIZONS, OPTIONS, Level, OptionCode, buy_option, k_locked, wait_option
from app.ui.chart_panel import chart_panel
from app.ui.context import PageContext

_CARD_GRID = "grid grid-cols-1 md:grid-cols-3 gap-4"


class PlayPage:
    def __init__(self, ctx: PageContext) -> None:
        self.ctx = ctx
        self.service = GameService(ctx.cfg, ctx.db)
        self.container = ui.column().classes("w-full gap-4")
        self.render()

    def render(self) -> None:
        self.container.clear()
        with self.container:
            self._render_body()

    def _render_body(self) -> None:
        user = self.ctx.active_user()
        if user is None:
            ui.label("Noch kein Nutzer angelegt.")
            ui.link("Zum Setup", "/setup")
            return
        try:
            rnd = self.service.current(user.id) or self.service.start_round(user.id)
        except PoolMissingError:
            ui.label("Kein Snapshot-Pool gefunden. Bitte zuerst `gt snapshots build` ausführen.")
            return

        if rnd.status == "open":
            stats = self.ctx.db.stats(user.id)
            _tiles(user, stats, rnd)
            DecisionView(self, user, rnd)
            _stats_card(stats)
        else:
            ResolutionView(self, user, rnd)


def play_page(ctx: PageContext) -> None:
    PlayPage(ctx)


def _tiles(user: UserRow, stats: Stats, rnd: RoundRow) -> None:
    with ui.row().classes("flex flex-col md:flex-row gap-4"):
        with ui.card().classes("gt-card"):
            ui.label(f"Guthaben: {cents_eur(user.balance_cents)}")
        with ui.card().classes("gt-card"):
            ui.label(f"Punkte gesamt: {fmt_points(stats.points_total)}")
        with ui.card().classes("gt-card"):
            ui.label(f"Runde: {round_number(stats.rounds, rnd.status == 'open')}")


def _stats_card(stats: Stats) -> None:
    with ui.card().classes("gt-card"):
        ui.label(
            f"Runden: {stats.rounds} · Punkte Ø: {stats.points_avg:.1f} · "
            f"Optimal: {stats.optimal_share:.0%}"
        )


class DecisionView:
    def __init__(self, page: PlayPage, user: UserRow, rnd: RoundRow) -> None:
        self.page = page
        self.user = user
        self.rnd = rnd
        self.level = Level.EINFACH
        self.selected: OptionCode | None = None
        self.data = page.service.load(rnd.ticker, rnd.t0)
        self.window = decision_window(self.data.ind, self.data.t0_idx)
        self.container = ui.column().classes("w-full gap-4")
        self._render()

    def _render(self) -> None:
        self.container.clear()
        with self.container:
            self._build()

    def _on_level_change(self, e: ValueChangeEventArguments[str]) -> None:
        self.level = Level(e.value)
        self.selected = None
        self._render()

    def _pick(self, option: OptionCode) -> None:
        self.selected = option
        self._render()

    def _build(self) -> None:
        setting = setting_for(self.user, self.level)
        cards = decision_cards(self.data.snap, setting)
        locked = k_locked(setting.balance, setting.start_capital)

        ui.toggle(
            ["Einfach", "Mittel", "Profi"], value=self.level.value, on_change=self._on_level_change
        ).mark("level")

        with (
            ui.element("div")
            .classes("w-full flex flex-col lg:flex-row lg:flex-nowrap lg:gap-6")
            .mark("decision-layout")
        ):
            with (
                ui.element("div")
                .classes("lg:w-[64%] flex flex-col gap-4")
                .mark("decision-chart-pane")
            ):
                self._chart(cards)
                if locked:
                    ui.label("Guthaben unter 1 % des Startkapitals: Kaufoptionen gesperrt.")
                    ui.link("Zum Setup", "/setup")
            with (
                ui.element("div")
                .classes("lg:w-[36%] flex flex-col gap-4")
                .mark("decision-options-pane")
            ):
                self._option_cards(cards, setting, locked)

    def _chart(self, cards: dict[OptionCode, Card]) -> None:
        def make_figure(theme: Theme) -> Figure:
            fig = build_figure(self.window, theme)
            if self.selected is not None:
                add_preview(fig, self.selected, cards.get(self.selected), theme)
            return fig

        chart_panel(self.page.ctx, self.window, make_figure, presets=True)

    def _option_cards(self, cards: dict[OptionCode, Card], setting: Setting, locked: bool) -> None:
        with ui.element("div").classes(_CARD_GRID):
            for horizon in HORIZONS:
                card = cards[buy_option(horizon)]
                self._option_card(card.option, card_lines(card, setting), disabled=locked)
        with ui.element("div").classes(_CARD_GRID):
            for horizon in HORIZONS:
                self._option_card(wait_option(horizon), wait_lines(horizon), disabled=False)

        confirm_btn = ui.button("Entscheidung bestätigen").mark("confirm")
        confirm_btn.on_click(lambda: self._confirm(confirm_btn))
        confirm_btn.set_enabled(self.selected is not None)

    def _option_card(self, option: OptionCode, lines: list[str], *, disabled: bool) -> None:
        classes = "gt-card" + (" gt-selected" if self.selected == option else "")
        with ui.card().classes(classes):
            for line in lines:
                ui.label(line)
            btn = ui.button("Auswählen", on_click=lambda: self._pick(option))
            btn.mark(f"pick-{option.value}")
            if disabled:
                btn.disable()

    def _confirm(self, btn: ui.button) -> None:
        if self.selected is None:
            return
        btn.disable()
        self.page.service.confirm(self.user, self.rnd, self.level, self.selected)
        self.page.render()


class ResolutionView:
    def __init__(self, page: PlayPage, user: UserRow, rnd: RoundRow) -> None:
        self.page = page
        self.user = user
        self.rnd = rnd
        self._build()

    def _build(self) -> None:
        service = self.page.service
        data = service.load(self.rnd.ticker, self.rnd.t0)
        res = service.resolution(self.rnd, self.user)
        stats = self.page.ctx.db.stats(self.user.id)

        with ui.element("div").classes("w-full gt-resolution-grid").mark("resolution-layout"):
            with ui.element("div").classes("gt-area-tiles").mark("resolution-tiles-pane"):
                _tiles(self.user, stats, self.rnd)
            self._chart_pane(data, res)
            with (
                ui.element("div")
                .classes("gt-area-result flex flex-col gap-4")
                .mark("resolution-result-pane")
            ):
                self._table(res)
                self._summary(stats)
            with ui.element("div").classes("gt-area-next").mark("resolution-next-pane"):
                ui.button("Nächste Runde", on_click=self._next_round)
            with ui.element("div").classes("gt-area-stats").mark("resolution-stats-pane"):
                _stats_card(stats)

    def _chart_pane(self, data: RoundData, res: Resolution) -> None:
        name = self.page.service.name_of(self.rnd.ticker)
        window = resolution_window(data.ind, data.t0_idx)

        def make_figure(theme: Theme) -> Figure:
            return build_resolution_figure(window, theme, res)

        with (
            ui.element("div")
            .classes("gt-area-chart flex flex-col gap-4")
            .mark("resolution-chart-pane")
        ):
            ui.label(f"{name} ({self.rnd.ticker}) · Tag 0: {date_de(self.rnd.t0)}")
            self._signal_line(data.ind, data.t0_idx)
            chart_panel(self.page.ctx, window, make_figure, presets=False)

    def _signal_line(self, ind: pd.DataFrame, t0_idx: int) -> None:
        flags = signal_flags(ind).iloc[t0_idx]
        events: list[str] = [
            label for event, label in EVENT_LABELS.items() if flags[f"sig_{event}"]
        ]
        ui.label("; ".join(events) if events else "Keine Signal-Ereignisse an Tag 0.")

    def _table(self, res: Resolution) -> None:
        if res.neutral:
            ui.label("Keine Option war vorteilhaft")
        columns = [
            {"name": n, "label": label, "field": n}
            for n, label in (
                ("option", "Option"),
                ("wert_pct", "Wert %"),
                ("wert_eur", "Wert €"),
                ("exit", "Exit"),
                ("kosten", "Kosten"),
                ("punkte", "Punkte"),
                ("markierung", "Markierung"),
            )
        ]
        rows = [self._row(res, option) for option in OPTIONS]
        ui.table(columns=columns, rows=rows, row_key="option")

    def _row(self, res: Resolution, option: OptionCode) -> dict[str, object]:
        o = res.outcomes[option]
        marks: list[str] = []
        if option == res.chosen:
            marks.append("Ihre Wahl")
        if o.optimal:
            marks.append("optimal")
        return {
            "option": option.value,
            "wert_pct": pct(o.value),
            "wert_eur": cents_eur(round(o.amount * 100)),
            "exit": EXIT_LABELS[o.reason] if o.reason is not None else "",
            "kosten": cents_eur(round(o.costs * 100)),
            "punkte": o.points,
            "markierung": " · ".join(marks),
        }

    def _summary(self, stats: Stats) -> None:
        before = self.rnd.balance_before_cents or 0
        after = self.rnd.balance_after_cents or 0
        ui.label(f"Guthaben vorher {cents_eur(before)} → nachher {cents_eur(after)}")
        total = fmt_points(stats.points_total)
        ui.label(f"Punkte dieser Runde: {self.rnd.points} · Punkte gesamt: {total}")

    def _next_round(self) -> None:
        self.page.service.start_round(self.user.id)
        self.page.render()
