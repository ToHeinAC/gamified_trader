"""Per-client page state shared by root, play and setup pages."""

from dataclasses import dataclass

from nicegui import ui

from app.config import Config
from app.db import Database, UserRow


@dataclass
class PageContext:
    cfg: Config
    db: Database
    dark: ui.dark_mode
    user_name: str = ""

    def active_user(self) -> UserRow | None:
        user_id = self.db.active_user_id()
        return self.db.user(user_id) if user_id is not None else None

    def refresh_user_name(self) -> None:
        user = self.active_user()
        self.user_name = user.name if user is not None else ""
