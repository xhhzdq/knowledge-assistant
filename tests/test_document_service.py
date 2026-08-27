"""Tests for the document-management service."""

from io import BytesIO
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import InvalidDocumentError, StorageError
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository
from knowledge_assistant.services.document_service import DocumentService


def build_service(tmp_path: Path) -> DocumentService:
    """Build an isolated service using pytest's temporary directory."""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    return DocumentService(repository, tmp_path / "data" / "uploads")


def test_add_document_copies_file_and_persists_metadata(tmp_path: Path) -> None:
    """Adding a document should retain both its bytes and metadata."""
    source = tmp_path / "source" / "学习资料.txt"
    source.parent.mkdir()
    source.write_text("第一周学习内容", encoding="utf-8")
    service = build_service(tmp_path)

    document = service.add_document(source)

    stored_file = Path(document.stored_path)
    assert stored_file.exists()
    assert stored_file.read_text(encoding="utf-8") == "第一周学习内容"
    assert document.name == "学习资料.txt"
    assert document.file_size == source.stat().st_size
    assert service.get_document(document.id) == document


def test_add_document_rejects_missing_source(tmp_path: Path) -> None:
    """A missing source path should fail before any metadata is written."""
    service = build_service(tmp_path)

    with pytest.raises(InvalidDocumentError, match="does not exist"):
        service.add_document(tmp_path / "missing.txt")

    assert service.list_documents() == []


def test_add_document_rejects_directory_source(tmp_path: Path) -> None:
    """Directories cannot be registered as documents."""
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    service = build_service(tmp_path)

    with pytest.raises(InvalidDocumentError, match="not a file"):
        service.add_document(source_directory)


def test_delete_document_removes_file_and_metadata(tmp_path: Path) -> None:
    """Deleting a document should remove both forms of stored data."""
    source = tmp_path / "source.txt"
    source.write_text("temporary content", encoding="utf-8")
    service = build_service(tmp_path)
    document = service.add_document(source)

    removed = service.delete_document(document.id)

    assert removed == document
    assert not Path(document.stored_path).exists()
    assert service.list_documents() == []


def test_delete_document_refuses_path_outside_uploads(tmp_path: Path) -> None:
    """Stored metadata must not be able to delete unrelated local files."""
    source = tmp_path / "source.txt"
    source.write_text("must remain", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    service = DocumentService(repository, tmp_path / "data" / "uploads")
    document = service.add_document(source)
    document.stored_path = str(source)
    repository.delete(document.id)
    repository.add(document)

    with pytest.raises(StorageError, match="outside the uploads"):
        service.delete_document(document.id)

    assert source.read_text(encoding="utf-8") == "must remain"


def test_uploaded_document_cleans_file_when_repository_add_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """数据库元数据写入失败时不能遗留已经上传的文件。"""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    uploads_dir = tmp_path / "data" / "uploads"
    service = DocumentService(repository, uploads_dir)

    def fail_add(*args: object) -> None:
        raise StorageError("simulated database failure")

    monkeypatch.setattr(repository, "add", fail_add)

    with pytest.raises(StorageError, match="simulated database failure"):
        service.add_uploaded_document("guide.txt", BytesIO(b"content"))

    assert list(uploads_dir.iterdir()) == []


def test_uploaded_document_cleans_file_when_size_limit_is_exceeded(tmp_path: Path) -> None:
    """上传内容超过限制时应清理已写入的部分文件。"""
    service = build_service(tmp_path)
    service.MAX_UPLOAD_SIZE = 4

    with pytest.raises(InvalidDocumentError, match="exceeds"):
        service.add_uploaded_document("large.txt", BytesIO(b"12345"))

    uploads_dir = tmp_path / "data" / "uploads"
    assert list(uploads_dir.iterdir()) == []


def test_delete_restores_file_when_repository_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """元数据删除失败时应把暂存文件恢复到原路径。"""
    source = tmp_path / "source.txt"
    source.write_text("must be restored", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    service = DocumentService(repository, tmp_path / "data" / "uploads")
    document = service.add_document(source)

    def fail_delete(*args: object) -> None:
        raise StorageError("simulated database failure")

    monkeypatch.setattr(repository, "delete", fail_delete)

    with pytest.raises(StorageError, match="simulated database failure"):
        service.delete_document(document.id)

    assert Path(document.stored_path).read_text(encoding="utf-8") == "must be restored"
    assert repository.get_by_id(document.id) == document
