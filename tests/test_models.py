"""Tests for the document domain model."""

from datetime import UTC, datetime

from knowledge_assistant.models import Document, DocumentData


def test_create_uses_supplied_document_values() -> None:
    """Create should retain the paths and size supplied by the caller."""
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
    """Create should generate an ID, status, and timezone-aware timestamp."""
    document = Document.create(
        original_path="D:/examples/notes.txt",
        stored_path="data/uploads/notes.txt",
        file_size=128,
    )

    created_at = datetime.fromisoformat(document.created_at)

    assert document.id
    assert document.status == "uploaded"
    assert created_at.tzinfo == UTC


def test_create_generates_a_unique_id() -> None:
    """Each created document should receive its own ID."""
    first = Document.create("first.txt", "data/uploads/first.txt", 10)
    second = Document.create("second.txt", "data/uploads/second.txt", 20)

    assert first.id != second.id


def test_to_dict_returns_all_document_fields() -> None:
    """to_dict should expose every document field using JSON-compatible values."""
    document = Document(
        id="document-1",
        name="guide.pdf",
        original_path="D:\\examples\\guide.pdf",
        stored_path="data/uploads/guide.pdf",
        file_type=".pdf",
        file_size=4096,
        status="uploaded",
        created_at="2026-08-09T10:00:00+00:00",
    )

    assert document.to_dict() == {
        "id": "document-1",
        "name": "guide.pdf",
        "original_path": "D:\\examples\\guide.pdf",
        "stored_path": "data/uploads/guide.pdf",
        "file_type": ".pdf",
        "file_size": 4096,
        "status": "uploaded",
        "created_at": "2026-08-09T10:00:00+00:00",
    }


def test_from_dict_restores_document() -> None:
    """from_dict should restore every field from document data."""
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

    assert document == Document(
        id="document-2",
        name="notes.txt",
        original_path="D:\\examples\\notes.txt",
        stored_path="data/uploads/notes.txt",
        file_type=".txt",
        file_size=256,
        status="uploaded",
        created_at="2026-08-09T11:00:00+00:00",
    )


def test_document_dictionary_round_trip_preserves_data() -> None:
    """Converting a document to a dictionary and back should lose no information."""
    original = Document.create(
        original_path="D:/examples/report.docx",
        stored_path="data/uploads/report.docx",
        file_size=8192,
    )

    restored = Document.from_dict(original.to_dict())

    assert restored == original
