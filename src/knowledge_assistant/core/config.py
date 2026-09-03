"""Application configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, Field, StringConstraints, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MilvusCollectionName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    ),
]


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


class ProcessingSettings(BaseSettings):
    """控制文本切分窗口，保证重叠区间始终小于目标长度。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    chunk_target_chars: int = Field(default=800, gt=0, le=1_000_000)
    chunk_max_chars: int = Field(default=1000, gt=0, le=1_000_000)
    chunk_overlap_chars: int = Field(default=100, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_chunk_window(self) -> Self:
        """拒绝无法形成有效 Chunk 滑动窗口的配置。"""
        if self.chunk_target_chars > self.chunk_max_chars:
            raise ValueError("CHUNK_TARGET_CHARS must not exceed CHUNK_MAX_CHARS")
        if self.chunk_overlap_chars >= self.chunk_target_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_TARGET_CHARS")
        return self


class OcrSettings(BaseSettings):
    """控制无文本页面的 OCR 回退策略。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    ocr_enabled: bool = True
    ocr_provider: Literal["paddle"] = "paddle"
    ocr_device: Literal["cpu", "gpu"] = "cpu"
    ocr_min_text_chars_per_page: int = Field(default=20, ge=0, le=1_000_000)


class EmbeddingSettings(BaseSettings):
    """描述 Embedding 模型及其输出契约，不在配置阶段加载模型。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    embedding_provider: Literal["bge"] = "bge"
    embedding_model: NonEmptyString = "BAAI/bge-small-zh-v1.5"
    embedding_model_path: NonEmptyString = "/models/bge-small-zh-v1.5"
    embedding_dimension: int = Field(default=512, gt=0, le=65_535)
    embedding_batch_size: int = Field(default=16, gt=0, le=1024)
    embedding_device: Literal["cpu", "gpu"] = "cpu"


class MilvusSettings(BaseSettings):
    """从环境变量读取 Milvus 连接与 Collection 配置。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    milvus_uri: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:19530")
    milvus_collection: MilvusCollectionName = "document_chunks_v1"
    milvus_metric_type: Literal["COSINE", "IP", "L2"] = "COSINE"
    milvus_timeout_seconds: float = Field(default=5.0, gt=0, le=300)
