"""Application configuration from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    yahoo_pause_s: float

    @property
    def prices_dir(self) -> Path:
        return self.data_dir / "prices"


def load_config(env: Mapping[str, str] | None = None) -> Config:
    source = os.environ if env is None else env
    return Config(
        data_dir=Path(source.get("GT_DATA_DIR", "data")),
        yahoo_pause_s=float(source.get("GT_YAHOO_PAUSE_S", "2.0")),
    )
