"""Tests for the document-management service."""

from io import BytesIO
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import InvalidDocumentError, StorageError
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository
from knowledge_assistant.services.document_service import DocumentService
from knowledge_assistant.storage.local_storage import LocalDocumentStorage


class MemoryDocumentCache:
    """用于验证 Service Cache Aside 行为的内存缓存。"""

    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.set_ttls: list[int] = []
        self.deleted_ids: list[str] = []
        self.fail_delete = False

    def get(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    def set(self, document: Document, ttl_seconds: int) -> None:
        self.documents[document.id] = document
        self.set_ttls.append(ttl_seconds)

    def delete(self, document_id: str) -> None:
        self.documents.pop(document_id, None)
        self.deleted_ids.append(document_id)
        if self.fail_delete:
            raise RuntimeError("simulated Redis failure")


class MemoryVectorRepository:
    """记录文档级向量删除，并可模拟 Milvus 清理失败。"""

    def __init__(self) -> None:
        self.deleted_document_ids: list[str] = []
        self.fail_delete = False

    def delete_by_document_id(self, document_id: str) -> int:
        self.deleted_document_ids.append(document_id)
        if self.fail_delete:
            raise RuntimeError("simulated Milvus failure")
        return 1


def build_service(tmp_path: Path) -> DocumentService:
    """Build an isolated service using pytest's temporary directory."""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(
        upload_dir=tmp_path / "data" / "uploads",
        max_file_size=10 * 1024 * 1024,
    )
    return DocumentService(repository, storage)


def test_add_document_copies_file_and_persists_metadata(tmp_path: Path) -> None:
    """Adding a document should retain both its bytes and metadata."""
    source = tmp_path / "source" / "学习资料.txt"
    source.parent.mkdir()
    source.write_text("第一周学习内容", encoding="utf-8")
    service = build_service(tmp_path)

    document = service.add_document(source)

    stored_file = tmp_path / "data" / "uploads" / document.stored_path
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
    assert not (tmp_path / "data" / "uploads" / document.stored_path).exists()
    assert service.list_documents() == []


def test_delete_document_keeps_outside_file_but_removes_metadata(tmp_path: Path) -> None:
    """外部文件清理失败不能恢复已删除的数据库事实来源。"""
    source = tmp_path / "source.txt"
    source.write_text("must remain", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(
        upload_dir=tmp_path / "data" / "uploads",
        max_file_size=10 * 1024 * 1024,
    )
    service = DocumentService(repository, storage)
    document = service.add_document(source)
    document.stored_path = str(source)
    repository.delete(document.id)
    repository.add(document)

    service.delete_document(document.id)

    assert source.read_text(encoding="utf-8") == "must remain"
    assert service.list_documents() == []


def test_uploaded_document_cleans_file_when_repository_add_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """数据库元数据写入失败时不能遗留已经上传的文件。"""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    uploads_dir = tmp_path / "data" / "uploads"
    storage = LocalDocumentStorage(upload_dir=uploads_dir, max_file_size=10 * 1024 * 1024)
    service = DocumentService(repository, storage)

    def fail_add(*args: object) -> None:
        raise StorageError("simulated database failure")

    monkeypatch.setattr(repository, "add", fail_add)

    with pytest.raises(StorageError, match="simulated database failure"):
        service.add_uploaded_document("guide.txt", BytesIO(b"content"))

    assert list(uploads_dir.glob("documents/*")) == []


def test_uploaded_document_cleans_file_when_size_limit_is_exceeded(tmp_path: Path) -> None:
    """上传内容超过限制时应清理已写入的部分文件。"""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    uploads_dir = tmp_path / "data" / "uploads"
    # 创建一个限制为 4 字节的存储
    storage = LocalDocumentStorage(upload_dir=uploads_dir, max_file_size=4)
    service = DocumentService(repository, storage)

    with pytest.raises(InvalidDocumentError, match="exceeds"):
        service.add_uploaded_document("large.txt", BytesIO(b"12345"))

    assert list(uploads_dir.glob("documents/*")) == []


def test_delete_restores_file_when_repository_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """元数据删除失败时应把暂存文件恢复到原路径。"""
    source = tmp_path / "source.txt"
    source.write_text("must be restored", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(
        upload_dir=tmp_path / "data" / "uploads",
        max_file_size=10 * 1024 * 1024,
    )
    service = DocumentService(repository, storage)
    document = service.add_document(source)

    def fail_delete(*args: object) -> None:
        raise StorageError("simulated database failure")

    monkeypatch.setattr(repository, "delete", fail_delete)

    with pytest.raises(StorageError, match="simulated database failure"):
        service.delete_document(document.id)

    stored_file = tmp_path / "data" / "uploads" / document.stored_path
    assert stored_file.read_text(encoding="utf-8") == "must be restored"
    assert repository.get_by_id(document.id) == document


def test_get_document_uses_cache_aside_and_configured_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第一次查询回源并写缓存，第二次查询直接命中缓存。"""
    source = tmp_path / "cache.txt"
    source.write_text("cache aside", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(tmp_path / "data" / "uploads")
    cache = MemoryDocumentCache()
    service = DocumentService(repository, storage, cache=cache, cache_ttl_seconds=45)
    document = service.add_document(source)

    first = service.get_document(document.id)

    assert first == document
    assert cache.documents[document.id] == document
    assert cache.set_ttls == [45]

    def fail_repository_read(*args: object) -> Document:
        raise AssertionError("缓存命中时不应查询 Repository")

    monkeypatch.setattr(repository, "get_by_id", fail_repository_read)

    assert service.get_document(document.id) == document
    assert cache.set_ttls == [45]


def test_update_and_delete_invalidate_document_cache(tmp_path: Path) -> None:
    """PATCH 和 DELETE 成功后必须删除对应详情缓存。"""
    source = tmp_path / "invalidate.txt"
    source.write_text("invalidate", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(tmp_path / "data" / "uploads")
    cache = MemoryDocumentCache()
    service = DocumentService(repository, storage, cache=cache)
    document = service.add_document(source)
    cache.set(document, ttl_seconds=300)

    updated = service.update_document(document.id, name="renamed.txt")

    assert updated.name == "renamed.txt"
    assert document.id not in cache.documents
    assert cache.deleted_ids == [document.id]

    cache.set(updated, ttl_seconds=300)
    service.delete_document(document.id)

    assert document.id not in cache.documents
    assert cache.deleted_ids == [document.id, document.id]


def test_delete_cleans_vectors_and_tolerates_external_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """数据库删除成功后，MinIO/Milvus 失败只记录告警且不会恢复文档。"""
    source = tmp_path / "cleanup.txt"
    source.write_text("cleanup", encoding="utf-8")
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    storage = LocalDocumentStorage(tmp_path / "data" / "uploads")
    cache = MemoryDocumentCache()
    vectors = MemoryVectorRepository()
    service = DocumentService(repository, storage, cache=cache, vectors=vectors)
    document = service.add_document(source)
    vectors.fail_delete = True
    cache.fail_delete = True

    def fail_storage_delete(*args: object) -> None:
        raise StorageError("simulated MinIO failure")

    monkeypatch.setattr(storage, "delete", fail_storage_delete)

    removed = service.delete_document(document.id)

    assert removed.id == document.id
    assert repository.list_all() == []
    assert vectors.deleted_document_ids == [document.id]
    assert cache.deleted_ids == [document.id]
