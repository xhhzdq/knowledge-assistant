"""Domain models for the Knowledge Assistant."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, TypedDict
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
        )

    @classmethod
    def create(cls, original_path: str, stored_path: str, file_size: int) -> Self:
        """Create document metadata and fill the application-managed fields."""
        source_path = Path(original_path)

        return cls(
            id=str(uuid4()),
            name=source_path.name,
            original_path=str(source_path),
            stored_path=stored_path,
            file_type=source_path.suffix.lower(),
            file_size=file_size,
            status="uploaded",
            created_at=datetime.now(UTC).isoformat(),
        )
