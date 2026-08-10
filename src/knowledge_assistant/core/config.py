"""Application configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class Settings:
    """Filesystem locations used by the local learning application."""

    project_root: Path
    data_dir: Path
    uploads_dir: Path
    metadata_file: Path

    @classmethod
    def default(cls) -> Self:
        """Build settings relative to this project's root directory."""
        project_root = Path(__file__).resolve().parents[3]
        data_dir = project_root / "data"

        return cls(
            project_root=project_root,
            data_dir=data_dir,
            uploads_dir=data_dir / "uploads",
            metadata_file=data_dir / "documents.json",
        )

    def ensure_data_directories(self) -> None:
        """Create runtime data directories when they do not exist."""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
