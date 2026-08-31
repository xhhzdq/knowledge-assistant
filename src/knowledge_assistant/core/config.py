"""Application configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

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


class StorageSettings(BaseSettings):
    """选择 API 使用本地文件系统还是 MinIO。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    document_storage_backend: Literal["local", "minio"] = "local"


class MinioSettings(BaseSettings):
    """从环境变量或项目根目录的 .env 文件读取 MinIO 配置。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    minio_endpoint: str = Field(default="", min_length=1)
    minio_access_key: str = Field(default="", min_length=1)
    minio_secret_key: str = Field(default="", min_length=8)
    minio_bucket: str = Field(default="", min_length=3, max_length=63)
    minio_secure: bool = False
    minio_max_file_size: int = Field(default=10 * 1024 * 1024, gt=0)

    @property
    def client_endpoint(self) -> str:
        """转换为 MinIO SDK 要求的不含协议的 ``host:port``。"""
        endpoint = self.minio_endpoint.strip().rstrip("/")
        if endpoint.startswith("http://"):
            endpoint = endpoint.removeprefix("http://")
        elif endpoint.startswith("https://"):
            endpoint = endpoint.removeprefix("https://")

        if not endpoint or "/" in endpoint:
            raise ValueError("MINIO_ENDPOINT must contain only host and optional port")
        return endpoint


class RedisSettings(BaseSettings):
    """从环境变量或项目根目录的 .env 文件读取 Redis 缓存配置。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    redis_url: str = Field(default="", min_length=1)
    document_cache_ttl_seconds: int = Field(default=300, gt=0, le=86400)
    redis_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    redis_socket_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
