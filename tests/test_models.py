"""Tests for document and processing domain models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from knowledge_assistant.models import Document, DocumentData
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage, TextChunk
from knowledge_assistant.repositories.sqlalchemy_repository import (
    SqlAlchemyDocumentRepository,
)


def test_create_uses_supplied_document_values() -> None:
    document = Document.create(
        original_path="D:/examples/Project Plan.PDF",
        stored_path="data/uploads/document.pdf",
        file_size=2048,
    )
    assert document.name == "Project Plan.PDF"
    assert document.original_path == "D:\\examples\\Project Plan.PDF"
    assert document.stored_path == "data/uploads/document.pdf"
    assert document.file_type == ".pdf"
    assert document.file_size == 2048


def test_create_fills_managed_fields() -> None:
    document = Document.create(
        original_path="D:/examples/notes.txt",
        stored_path="data/uploads/notes.txt",
        file_size=128,
    )
    created_at = datetime.fromisoformat(document.created_at)
    assert document.id
    assert document.status == "uploaded"
    assert created_at.tzinfo == UTC
    assert document.updated_at == document.created_at
    assert document.processing_version == 0


def test_create_generates_a_unique_id() -> None:
    first = Document.create("first.txt", "data/uploads/first.txt", 10)
    second = Document.create("second.txt", "data/uploads/second.txt", 20)
    assert first.id != second.id


def test_to_dict_returns_all_document_fields() -> None:
    document = Document(
        id="document-1",
        name="guide.pdf",
        original_path="D:\\examples\\guide.pdf",
        stored_path="data/uploads/guide.pdf",
        file_type=".pdf",
        file_size=4096,
        status="ready",
        created_at="2026-08-09T10:00:00+00:00",
        updated_at="2026-08-09T10:30:00+00:00",
        processing_version=1,
        content_hash="a" * 64,
        processed_at="2026-08-09T10:31:00+00:00",
        processing_error=None,
    )
    assert document.to_dict() == {
        "id": "document-1",
        "name": "guide.pdf",
        "original_path": "D:\\examples\\guide.pdf",
        "stored_path": "data/uploads/guide.pdf",
        "file_type": ".pdf",
        "file_size": 4096,
        "status": "ready",
        "created_at": "2026-08-09T10:00:00+00:00",
        "updated_at": "2026-08-09T10:30:00+00:00",
        "processing_version": 1,
        "content_hash": "a" * 64,
        "processed_at": "2026-08-09T10:31:00+00:00",
        "processing_error": None,
    }


def test_from_legacy_dict_fills_new_document_fields() -> None:
    data: DocumentData = {
        "id": "document-2",
        "name": "notes.txt",
        "original_path": "D:\\examples\\notes.txt",
        "stored_path": "data/uploads/notes.txt",
        "file_type": ".txt",
        "file_size": 256,
        "status": "uploaded",
        "created_at": "2026-08-09T11:00:00+00:00",
    }
    document = Document.from_dict(data)
    assert document.updated_at == data["created_at"]
    assert document.processing_version == 0
    assert document.content_hash is None
    assert document.processed_at is None
    assert document.processing_error is None


def test_document_dictionary_round_trip_preserves_processing_fields() -> None:
    original = Document(
        id=str(uuid4()),
        name="processed.pdf",
        original_path="D:\\examples\\processed.pdf",
        stored_path="documents/processed.pdf",
        file_type=".pdf",
        file_size=2048,
        status="ready",
        created_at="2026-09-01T01:00:00+00:00",
        updated_at="2026-09-01T01:05:00+00:00",
        processing_version=2,
        content_hash="b" * 64,
        processed_at="2026-09-01T01:05:00+00:00",
        processing_error=None,
    )
    assert Document.from_dict(original.to_dict()) == original


def test_document_orm_round_trip_preserves_processing_fields_and_utc() -> None:
    original = Document(
        id=str(uuid4()),
        name="processed.pdf",
        original_path="D:\\examples\\processed.pdf",
        stored_path="documents/processed.pdf",
        file_type=".pdf",
        file_size=2048,
        status="ready",
        created_at="2026-09-01T09:00:00+08:00",
        updated_at="2026-09-01T09:05:00+08:00",
        processing_version=2,
        content_hash="f" * 64,
        processed_at="2026-09-01T09:05:00+08:00",
        processing_error=None,
    )

    row = SqlAlchemyDocumentRepository._from_domain(original)
    restored = SqlAlchemyDocumentRepository._to_domain(row)

    assert restored.processing_version == original.processing_version
    assert restored.content_hash == original.content_hash
    assert restored.created_at == "2026-09-01T01:00:00+00:00"
    assert restored.updated_at == "2026-09-01T01:05:00+00:00"
    assert restored.processed_at == "2026-09-01T01:05:00+00:00"


def test_parsed_document_keeps_ordered_pages_and_parser_metadata() -> None:
    pages = [
        ParsedPage(1, "first page", "parser"),
        ParsedPage(2, "second page", "ocr", 0.97),
    ]
    parsed = ParsedDocument(
        pages=pages,
        content_hash="c" * 64,
        parser_name="pypdf",
        parser_version="6.0",
    )
    assert parsed.pages == pages
    assert parsed.pages[1].ocr_confidence == 0.97


def test_text_chunk_accepts_valid_ranges_and_normalizes_created_at_to_utc() -> None:
    chunk = TextChunk(
        id=str(uuid4()),
        document_id=str(uuid4()),
        processing_version=1,
        chunk_index=0,
        content="stable chunk text",
        content_hash="d" * 64,
        char_start=0,
        char_end=17,
        page_start=1,
        page_end=1,
        source_type="parser",
        ocr_confidence=None,
        token_count=4,
        created_at=datetime.fromisoformat("2026-09-01T09:00:00+08:00"),
    )
    assert chunk.created_at.isoformat() == "2026-09-01T01:00:00+00:00"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"processing_version": 0}, "processing_version"),
        ({"chunk_index": -1}, "chunk_index"),
        ({"content": "  "}, "content"),
        ({"char_end": 0}, "character range"),
        ({"page_start": 2, "page_end": 1}, "page range"),
        ({"ocr_confidence": 1.1}, "ocr_confidence"),
        ({"token_count": 0}, "token_count"),
    ],
)
def test_text_chunk_rejects_invalid_ranges(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "id": str(uuid4()),
        "document_id": str(uuid4()),
        "processing_version": 1,
        "chunk_index": 0,
        "content": "valid content",
        "content_hash": "e" * 64,
        "char_start": 0,
        "char_end": 13,
        "page_start": 1,
        "page_end": 1,
        "source_type": "parser",
        "ocr_confidence": None,
        "token_count": 3,
        "created_at": datetime.now(UTC),
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        TextChunk(**values)  # type: ignore[arg-type]
