"""Tests for the JSON document repository."""

from pathlib import Path

import pytest

from knowledge_assistant.exceptions import DocumentNotFoundError, StorageError
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository


def make_document(document_id: str = "document-1") -> Document:
    """Build stable document metadata for repository tests."""
    return Document(
        id=document_id,
        name="guide.txt",
        original_path="D:\\examples\\guide.txt",
        stored_path="D:\\data\\uploads\\guide.txt",
        file_type=".txt",
        file_size=128,
        status="uploaded",
        created_at="2026-08-09T10:00:00+00:00",
    )


def test_list_all_returns_empty_when_metadata_file_is_missing(tmp_path: Path) -> None:
    """A new repository should behave like an empty collection."""
    repository = JsonDocumentRepository(tmp_path / "documents.json")

    assert repository.list_all() == []


def test_add_persists_document_for_a_new_repository_instance(tmp_path: Path) -> None:
    """Written metadata should be recoverable after rebuilding the repository."""
    metadata_file = tmp_path / "documents.json"
    JsonDocumentRepository(metadata_file).add(make_document())

    reloaded_repository = JsonDocumentRepository(metadata_file)

    assert reloaded_repository.list_all() == [make_document()]


def test_get_by_id_returns_matching_document(tmp_path: Path) -> None:
    """A document should be found by its unique ID."""
    repository = JsonDocumentRepository(tmp_path / "documents.json")
    repository.add(make_document())

    assert repository.get_by_id("document-1") == make_document()


def test_get_by_id_raises_when_document_is_missing(tmp_path: Path) -> None:
    """Unknown IDs should produce an application-specific error."""
    repository = JsonDocumentRepository(tmp_path / "documents.json")

    with pytest.raises(DocumentNotFoundError, match="missing"):
        repository.get_by_id("missing")


def test_delete_removes_persisted_document(tmp_path: Path) -> None:
    """Delete should return the removed document and persist the new list."""
    repository = JsonDocumentRepository(tmp_path / "documents.json")
    document = make_document()
    repository.add(document)

    removed = repository.delete(document.id)

    assert removed == document
    assert repository.list_all() == []


def test_update_replaces_persisted_document(tmp_path: Path) -> None:
    """更新后重新创建 Repository 也应读取到新数据。"""
    metadata_file = tmp_path / "documents.json"
    repository = JsonDocumentRepository(metadata_file)
    original = make_document()
    repository.add(original)
    updated = Document(**{**original.to_dict(), "name": "updated.txt", "status": "ready"})

    result = repository.update(updated)

    assert result == updated
    assert JsonDocumentRepository(metadata_file).get_by_id(original.id) == updated


def test_invalid_json_raises_storage_error(tmp_path: Path) -> None:
    """Corrupted metadata should not be treated as an empty repository."""
    metadata_file = tmp_path / "documents.json"
    metadata_file.write_text("not valid json", encoding="utf-8")
    repository = JsonDocumentRepository(metadata_file)

    with pytest.raises(StorageError, match="Unable to read metadata"):
        repository.list_all()
