"""Domain models for the Knowledge Assistant."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, Self, TypedDict
from uuid import uuid4


class DocumentData(TypedDict):
    """Dictionary representation of document metadata."""

    id: str
    name: str
    original_path: str
    stored_path: str
    file_type: str
    file_size: int
    status: str
    created_at: str
    updated_at: NotRequired[str]
    processing_version: NotRequired[int]
    content_hash: NotRequired[str | None]
    processed_at: NotRequired[str | None]
    processing_error: NotRequired[str | None]


@dataclass
class Document:
    """Metadata describing a document managed by the application."""

    id: str
    name: str
    original_path: str
    stored_path: str
    file_type: str
    file_size: int
    status: str
    created_at: str
    updated_at: str = ""
    processing_version: int = 0
    content_hash: str | None = None
    processed_at: str | None = None
    processing_error: str | None = None

    def __post_init__(self) -> None:
        """补齐旧调用方未提供的更新时间，并校验处理版本。"""
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.processing_version < 0:
            raise ValueError("processing_version must be non-negative")

    def to_dict(self) -> DocumentData:
        """Convert this document into a dictionary suitable for JSON encoding."""
        return {
            "id": self.id,
            "name": self.name,
            "original_path": self.original_path,
            "stored_path": self.stored_path,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processing_version": self.processing_version,
            "content_hash": self.content_hash,
            "processed_at": self.processed_at,
            "processing_error": self.processing_error,
        }

    @classmethod
    def from_dict(cls, data: DocumentData) -> Self:
        """Restore document metadata from its dictionary representation."""
        return cls(
            id=data["id"],
            name=data["name"],
            original_path=data["original_path"],
            stored_path=data["stored_path"],
            file_type=data["file_type"],
            file_size=data["file_size"],
            status=data["status"],
            created_at=data["created_at"],
            updated_at=data.get("updated_at", data["created_at"]),
            processing_version=data.get("processing_version", 0),
            content_hash=data.get("content_hash"),
            processed_at=data.get("processed_at"),
            processing_error=data.get("processing_error"),
        )

    @classmethod
    def create(cls, original_path: str, stored_path: str, file_size: int) -> Self:
        """Create document metadata and fill the application-managed fields."""
        source_path = Path(original_path)

        now = datetime.now(UTC).isoformat()
        return cls(
            id=str(uuid4()),
            name=source_path.name,
            original_path=str(source_path),
            stored_path=stored_path,
            file_type=source_path.suffix.lower(),
            file_size=file_size,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
