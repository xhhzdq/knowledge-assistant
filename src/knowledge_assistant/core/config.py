"""Application configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Settings:
    """Filesystem locations used by the local learning application."""

    project_root: Path
    data_dir: Path
    uploads_dir: Path
    metadata_file: Path
    logs_dir: Path
    log_file: Path

    @classmethod
    def default(cls) -> Self:
        """Build settings relative to this project's root directory."""
        project_root = Path(__file__).resolve().parents[3]
        data_dir = project_root / "data"
        logs_dir = project_root / "logs"

        return cls(
            project_root=project_root,
            data_dir=data_dir,
            uploads_dir=data_dir / "uploads",
            metadata_file=data_dir / "documents.json",
            logs_dir=logs_dir,
            log_file=logs_dir / "app.log",
        )

    def ensure_runtime_directories(self) -> None:
        """创建应用运行时需要的数据和日志目录。"""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


class DatabaseSettings(BaseSettings):
    """从环境变量或项目根目录的 .env 文件读取数据库配置。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    database_url: str = Field(default="", min_length=1)
    test_database_url: str = Field(default="", min_length=1)
