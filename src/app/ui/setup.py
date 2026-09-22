"""Page "Setup": create/select users, edit settings, reset balance."""

from datetime import UTC, datetime

from nicegui import ui

from app.db import UserRow
from app.fmt import cents_eur
from app.settings_rules import (
    CAPITAL_DEFAULT,
    ValidationError,
    validate_name,
    validate_settings,
    validate_start_capital,
)
from app.ui.context import PageContext


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SetupView:
    def __init__(self, ctx: PageContext) -> None:
        self.ctx = ctx
        self.container = ui.column()
        self.render()

    def render(self) -> None:
        self.container.clear()
        with self.container:
            self._new_user_card()
            user = self.ctx.active_user()
            self._active_user_card()
            if user is not None:
                self._settings_card(user)
                self._balance_card(user)

    def _new_user_card(self) -> None:
        with ui.card().classes("gt-card"):
            ui.label("Neuer Nutzer")
            name_input = ui.input("Name").mark("name")
            capital_input = ui.number("Startkapital (€)", value=CAPITAL_DEFAULT, step=1000).mark(
                "new-capital"
            )
            error = ui.label("").classes("text-negative")

            def _create() -> None:
                try:
                    existing = [u.name for u in self.ctx.db.users()]
                    name = validate_name(name_input.value or "", existing)
                    capital = validate_start_capital(capital_input.value)
                except ValidationError as exc:
                    error.set_text(str(exc))
                    return
                user_id = self.ctx.db.create_user(name, capital, _now())
                self.ctx.db.set_active_user(user_id)
                self.ctx.refresh_user_name()
                ui.notify("Gespeichert")
                self.render()

            ui.button("Anlegen", on_click=_create)

    def _active_user_card(self) -> None:
        users = self.ctx.db.users()
        if not users:
            return
        with ui.card().classes("gt-card"):
            ui.label("Aktiver Nutzer")
            options = {u.id: u.name for u in users}
            active_id = self.ctx.db.active_user_id()
            select = ui.select(options, value=active_id, label="Nutzer").mark("active-user")

            def _on_change() -> None:
                if select.value is not None:
                    self.ctx.db.set_active_user(int(select.value))
                    self.ctx.refresh_user_name()
                    self.render()

            select.on_value_change(_on_change)

    def _settings_card(self, user: UserRow) -> None:
        with ui.card().classes("gt-card"):
            ui.label("Einstellungen")
            capital = ui.number("Startkapital (€)", value=user.start_capital_cents / 100).mark(
                "capital"
            )
            mid = ui.number("Hebel Mittel", value=user.lev_mid).mark("lev-mid")
            pro = ui.number("Hebel Profi", value=user.lev_pro).mark("lev-pro")
            interest = ui.number("Zinssatz (% p. a.)", value=user.interest_tenths / 10).mark(
                "interest"
            )
            fee = ui.number("Gebührensatz (%)", value=user.fee_tenths / 10).mark("fee")
            ui.label("Einfach: Hebel 1 (fest)")
            error = ui.label("").classes("text-negative")

            def _save() -> None:
                try:
                    settings = validate_settings(
                        capital.value, mid.value, pro.value, interest.value, fee.value
                    )
                except ValidationError as exc:
                    error.set_text(str(exc))
                    return
                self.ctx.db.update_settings(user.id, settings)
                ui.notify("Gespeichert")
                self.render()

            ui.button("Speichern", on_click=_save)
            ui.label("Neues Startkapital gilt ab dem nächsten Zurücksetzen.")

    def _balance_card(self, user: UserRow) -> None:
        with ui.card().classes("gt-card"):
            ui.label("Guthaben")
            ui.label(f"Guthaben: {cents_eur(user.balance_cents)}")
            ui.label(f"Startkapital: {cents_eur(user.start_capital_cents)}")
            count = self.ctx.db.reset_count(user.id)
            ui.label(f"Zurückgesetzt: {count}-mal")

            with ui.dialog() as dialog, ui.card():
                ui.label(
                    f"Guthaben auf {cents_eur(user.start_capital_cents)} zurücksetzen? "
                    "Punkte und Runden bleiben erhalten."
                )
                with ui.row():
                    ui.button("Abbrechen", on_click=dialog.close).mark("cancel-reset")
                    ui.button(
                        "Zurücksetzen", on_click=lambda: self._confirm_reset(user, dialog)
                    ).mark("confirm-reset")

            ui.button("Guthaben zurücksetzen", on_click=dialog.open)

    def _confirm_reset(self, user: UserRow, dialog: ui.dialog) -> None:
        self.ctx.db.reset_balance(user.id, _now())
        dialog.close()
        self.render()


def setup_page(ctx: PageContext) -> None:
    SetupView(ctx)
