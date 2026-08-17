"""All persistent paths live in the platform-native application data directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    database: Path
    media: Path
    results: Path
    models: Path

    @classmethod
    def create(cls) -> "AppPaths":
        root = Path(user_data_path("ASR Workbench", "ASR Workbench", ensure_exists=True))
        paths = cls(
            root=root,
            database=root / "asr-workbench.sqlite3",
            media=root / "media",
            results=root / "results",
            models=root / "models",
        )
        for directory in (paths.media, paths.results, paths.models):
            directory.mkdir(parents=True, exist_ok=True)
        return paths
