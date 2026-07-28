"""Config load/save for .chronicle/config.toml.

Kept intentionally simple (flat keys + one string list) so we can write TOML
by hand and read it with the stdlib `tomllib`, without adding a TOML-writer
dependency for what is currently a handful of scalar settings.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDES = [
    ".git",
    ".chronicle",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
]


@dataclass
class Config:
    debounce_ms: int = 400
    max_batch_window_s: float = 5.0
    max_file_size_mb: float = 5.0
    attribution_window_s: float = 3.0
    group_gap_s: float = 60.0
    ui_port: int = 4317
    excludes: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            data = tomllib.load(f)
        core = data.get("core", {})
        return cls(
            debounce_ms=core.get("debounce_ms", cls.debounce_ms),
            max_batch_window_s=core.get("max_batch_window_s", cls.max_batch_window_s),
            max_file_size_mb=core.get("max_file_size_mb", cls.max_file_size_mb),
            attribution_window_s=core.get(
                "attribution_window_s", cls.attribution_window_s
            ),
            group_gap_s=core.get("group_gap_s", cls.group_gap_s),
            ui_port=core.get("ui_port", cls.ui_port),
            excludes=core.get("excludes", list(DEFAULT_EXCLUDES)),
        )

    def save(self, path: Path) -> None:
        excludes_toml = ", ".join(f'"{e}"' for e in self.excludes)
        text = (
            "[core]\n"
            f"debounce_ms = {self.debounce_ms}\n"
            f"max_batch_window_s = {self.max_batch_window_s}\n"
            f"max_file_size_mb = {self.max_file_size_mb}\n"
            f"attribution_window_s = {self.attribution_window_s}\n"
            f"group_gap_s = {self.group_gap_s}\n"
            f"ui_port = {self.ui_port}\n"
            f"excludes = [{excludes_toml}]\n"
        )
        path.write_text(text)
