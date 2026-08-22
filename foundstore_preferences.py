from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


THEMES = {"dark", "light"}
VIEW_MODES = {"compact", "measured", "macos"}
GRID_COLUMNS = {3, 4, 5}
ACCENTS = {
    "verdypor": "#77e9b2",
    "oceano": "#65b6ff",
    "violeta": "#b38cff",
    "coral": "#ff9d82",
    "oro": "#f1c967",
}


@dataclass(frozen=True)
class FoundstorePreferences:
    theme: str = "dark"
    accent: str = "verdypor"
    view_mode: str = "macos"
    grid_columns: int = 3

    @property
    def accent_color(self) -> str:
        return ACCENTS[self.accent]

    @classmethod
    def path(cls) -> Path:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        directory = base / "influent-danenone"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "foundstore-ui.json"

    @classmethod
    def load(cls) -> "FoundstorePreferences":
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return cls()
        return cls(
            theme=data.get("theme") if data.get("theme") in THEMES else "dark",
            accent=data.get("accent") if data.get("accent") in ACCENTS else "verdypor",
            view_mode=data.get("view_mode") if data.get("view_mode") in VIEW_MODES else "macos",
            grid_columns=data.get("grid_columns") if data.get("grid_columns") in GRID_COLUMNS else 3,
        )

    def save(self) -> None:
        target = self.path()
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"theme": self.theme, "accent": self.accent, "view_mode": self.view_mode, "grid_columns": self.grid_columns}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(target)
