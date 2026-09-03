"""Framework-independent domain models used by the processing pipeline."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

TextSource = Literal["parser", "ocr"]
ChunkSource = Literal["parser", "ocr", "mixed"]


def _validate_sha256(value: str, field_name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{field_name} must contain a 64-character SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must contain hexadecimal characters") from exc


def _validate_confidence(value: float | None) -> None:
    if value is not None and not 0 <= value <= 1:
        raise ValueError("ocr_confidence must be between 0 and 1")


@dataclass(frozen=True)
class ParsedPage:
    """Text extracted from one physical page or logical document unit."""

    page_number: int | None
    text: str
    source_type: TextSource
    ocr_confidence: float | None = None
    requires_ocr: bool = False

    def __post_init__(self) -> None:
        if self.page_number is not None and self.page_number <= 0:
            raise ValueError("page_number must be positive when present")
        if self.source_type not in {"parser", "ocr"}:
            raise ValueError("source_type must be parser or ocr")
        _validate_confidence(self.ocr_confidence)


@dataclass(frozen=True)
class ParsedDocument:
    """Ordered parser output plus reproducibility metadata."""

    pages: list[ParsedPage]
    content_hash: str
    parser_name: str
    parser_version: str

    def __post_init__(self) -> None:
        if not self.pages:
            raise ValueError("pages must not be empty")
        _validate_sha256(self.content_hash, "content_hash")
        if not self.parser_name.strip():
            raise ValueError("parser_name must not be blank")
        if not self.parser_version.strip():
            raise ValueError("parser_version must not be blank")


@dataclass(frozen=True)
class TextChunk:
    """A stable text unit persisted in PostgreSQL and referenced by Milvus."""

    id: str
    document_id: str
    processing_version: int
    chunk_index: int
    content: str
    content_hash: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    source_type: ChunkSource
    ocr_confidence: float | None
    token_count: int
    created_at: datetime

    def __post_init__(self) -> None:
        UUID(self.id)
        UUID(self.document_id)
        if self.processing_version <= 0:
            raise ValueError("processing_version must be positive")
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        _validate_sha256(self.content_hash, "content_hash")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("character range must be non-empty and non-negative")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start and page_end must either both be set or both be absent")
        if self.page_start is not None:
            if self.page_start <= 0 or self.page_end is None or self.page_end < self.page_start:
                raise ValueError("page range must be positive and ordered")
        if self.source_type not in {"parser", "ocr", "mixed"}:
            raise ValueError("source_type must be parser, ocr, or mixed")
        _validate_confidence(self.ocr_confidence)
        if self.token_count <= 0:
            raise ValueError("token_count must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
