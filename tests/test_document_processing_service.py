"""DocumentProcessingService 的跨组件编排测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from knowledge_assistant.exceptions import (
    EmbeddingError,
    NoExtractableTextError,
    OcrError,
    ProcessingInProgressError,
    StorageError,
    VectorStoreError,
)
from knowledge_assistant.models import Document
from knowledge_assistant.processing.chunker import TextChunker
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage, TextChunk
from knowledge_assistant.services.document_processing_service import DocumentProcessingService
from knowledge_assistant.vectors.base import VectorRecord


def make_document(
    *,
    status: str = "uploaded",
    version: int = 0,
    content: bytes = b"hello",
) -> Document:
    now = datetime.now(UTC).isoformat()
    return Document(
        id=str(uuid4()),
        name="guide.txt",
        original_path="guide.txt",
        stored_path="documents/guide.txt",
        file_type=".txt",
        file_size=len(content),
        status=status,
        created_at=now,
        updated_at=now,
        processing_version=version,
        content_hash=sha256(content).hexdigest() if status == "ready" else None,
        processed_at=now if status == "ready" else None,
    )


def make_old_chunk(document: Document) -> TextChunk:
    return TextChunk(
        id=str(uuid4()),
        document_id=document.id,
        processing_version=max(1, document.processing_version),
        chunk_index=0,
        content="old",
        content_hash=sha256(b"old").hexdigest(),
        char_start=0,
        char_end=3,
        page_start=None,
        page_end=None,
        source_type="parser",
        ocr_confidence=None,
        token_count=1,
        created_at=datetime.now(UTC),
    )


class FakeDocumentRepository:
    def __init__(self, document: Document, events: list[str]) -> None:
        self.document = document
        self.events = events
        self.fail_ready_update = False
        self.rollback_count = 0

    def get_by_id_for_update(self, document_id: str) -> Document:
        assert document_id == self.document.id
        self.events.append("document.lock")
        return self.document

    def get_by_id(self, document_id: str) -> Document:
        assert document_id == self.document.id
        self.events.append("document.get")
        return self.document

    def update(self, document: Document) -> Document:
        self.events.append(f"document.update.{document.status}")
        if document.status == "ready" and self.fail_ready_update:
            raise StorageError("secret database details")
        self.document = document
        return document

    def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("document.rollback")


class FakeChunkRepository:
    def __init__(self, chunks: list[TextChunk], events: list[str]) -> None:
        self.chunks = chunks
        self.events = events
        self.fail_replace = False
        self.last_commit: bool | None = None

    def replace_for_document(
        self,
        document_id: str,
        chunks: list[TextChunk],
        *,
        commit: bool = True,
    ) -> None:
        assert all(chunk.document_id == document_id for chunk in chunks)
        self.events.append("chunks.replace")
        self.last_commit = commit
        if self.fail_replace:
            raise StorageError("chunk commit failed")
        self.chunks = chunks

    def list_page(
        self,
        document_id: str,
        offset: int,
        limit: int,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> list[TextChunk]:
        return self._filtered(document_id, processing_version, page_number)[
            offset : offset + limit
        ]

    def count(
        self,
        document_id: str,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> int:
        return len(self._filtered(document_id, processing_version, page_number))

    def _filtered(
        self,
        document_id: str,
        processing_version: int | None,
        page_number: int | None,
    ) -> list[TextChunk]:
        return [
            chunk
            for chunk in self.chunks
            if chunk.document_id == document_id
            and (processing_version is None or chunk.processing_version == processing_version)
            and (
                page_number is None
                or (
                    chunk.page_start is not None
                    and chunk.page_end is not None
                    and chunk.page_start <= page_number <= chunk.page_end
                )
            )
        ]

    def get_many_by_ids(self, chunk_ids: list[str]) -> list[TextChunk]:
        return [chunk for chunk in self.chunks if chunk.id in chunk_ids]

    def delete_by_document(self, document_id: str) -> int:
        before = len(self.chunks)
        self.chunks = [chunk for chunk in self.chunks if chunk.document_id != document_id]
        return before - len(self.chunks)


class FakeStorage:
    def __init__(self, content: bytes, events: list[str]) -> None:
        self.content = content
        self.events = events
        self.fail_read = False
        self.deleted: list[str] = []

    def read(self, object_key: str) -> bytes:
        self.events.append("storage.read")
        if self.fail_read:
            raise StorageError("access_key=do-not-expose")
        return self.content

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


class FakeParser:
    parser_name = "fake-parser"
    parser_version = "1"
    supported_extensions = frozenset({".txt"})

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail = False

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        self.events.append("parser.parse")
        if self.fail:
            raise NoExtractableTextError("private source details")
        return ParsedDocument(
            pages=[ParsedPage(None, content.decode(), "parser")],
            content_hash=sha256(content).hexdigest(),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
        )


class FakeEmbedding:
    model_name = "fake-bge"
    dimension = 2

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail = False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.events.append("embedding.embed")
        if self.fail:
            raise EmbeddingError("model path is private")
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


class FakeVectors:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.records: list[VectorRecord] = []
        self.deleted_batches: list[list[str]] = []
        self.fail_upsert = False
        self.fail_old_cleanup = False

    def upsert(self, records: list[VectorRecord]) -> None:
        self.events.append("vectors.upsert")
        self.records = list(records)
        if self.fail_upsert:
            raise VectorStoreError("milvus unavailable")

    def delete_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        self.events.append("vectors.delete")
        self.deleted_batches.append(list(chunk_ids))
        if self.fail_old_cleanup:
            raise VectorStoreError("cleanup unavailable")
        return len(chunk_ids)


class FakeCache:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.deleted: list[str] = []

    def delete(self, document_id: str) -> None:
        self.events.append("cache.delete")
        self.deleted.append(document_id)


def build_service(
    document: Document,
    content: bytes = b"hello world. second sentence.",
    *,
    old_chunks: list[TextChunk] | None = None,
) -> tuple[
    DocumentProcessingService,
    FakeDocumentRepository,
    FakeChunkRepository,
    FakeStorage,
    FakeParser,
    FakeEmbedding,
    FakeVectors,
    FakeCache,
    list[str],
]:
    events: list[str] = []
    documents = FakeDocumentRepository(document, events)
    chunks = FakeChunkRepository(old_chunks or [], events)
    storage = FakeStorage(content, events)
    parser = FakeParser(events)
    embedding = FakeEmbedding(events)
    vectors = FakeVectors(events)
    cache = FakeCache(events)
    service = DocumentProcessingService(
        documents,
        chunks,
        storage,
        [parser],
        TextChunker(20, 30, 5, embedding.count_tokens),
        embedding,
        vectors,
        cache=cache,
    )
    return service, documents, chunks, storage, parser, embedding, vectors, cache, events


def test_successful_processing_uses_safe_cross_store_order() -> None:
    document = make_document()
    old_chunk = make_old_chunk(replace(document, processing_version=1))
    service, documents, chunks, storage, _, _, vectors, cache, events = build_service(
        document, old_chunks=[old_chunk]
    )

    result = service.process(document.id)

    assert result.status == "ready"
    assert result.processing_version == 1
    assert result.chunk_count == result.vector_count == len(vectors.records)
    assert result.parser_name == "fake-parser"
    assert result.reused is False
    assert chunks.last_commit is False
    assert vectors.deleted_batches[-1] == [old_chunk.id]
    assert storage.deleted == []
    assert cache.deleted == [document.id]
    assert events.index("vectors.upsert") < events.index("chunks.replace")
    assert events.index("chunks.replace") < events.index("document.update.ready")
    assert events.index("document.update.ready") < events.index("vectors.delete")
    assert documents.document.processing_error is None


def test_ready_unchanged_document_is_reused_without_reprocessing() -> None:
    content = b"hello"
    document = make_document(status="ready", version=3, content=content)
    old_chunk = make_old_chunk(document)
    service, documents, _, _, _, _, vectors, cache, events = build_service(
        document, content, old_chunks=[old_chunk]
    )

    result = service.process(document.id)

    assert result.reused is True
    assert result.processing_version == 3
    assert result.chunk_count == 1
    assert documents.rollback_count == 1
    assert vectors.records == []
    assert cache.deleted == [document.id]
    assert "parser.parse" not in events


def test_force_rebuilds_ready_document_with_new_version() -> None:
    content = b"hello world"
    document = make_document(status="ready", version=4, content=content)
    service, _, _, _, _, _, vectors, _, _ = build_service(document, content)

    result = service.process(document.id, force=True)

    assert result.reused is False
    assert result.processing_version == 5
    assert {record.processing_version for record in vectors.records} == {5}


def test_processing_status_rejects_concurrent_request_before_read() -> None:
    document = make_document(status="processing", version=2)
    service, documents, _, storage, _, _, _, _, _ = build_service(document)

    with pytest.raises(ProcessingInProgressError):
        service.process(document.id)

    assert documents.rollback_count == 1
    assert storage.events == ["document.lock", "document.rollback"]
    assert storage.deleted == []


def test_missing_ocr_provider_marks_forced_pdf_processing_failed() -> None:
    document = replace(make_document(), name="scan.pdf", file_type=".pdf")
    service, documents, _, storage, parser, _, _, cache, _ = build_service(document)
    parser.supported_extensions = frozenset({".pdf"})

    with pytest.raises(OcrError):
        service.process(document.id, ocr_mode="force")

    assert documents.document.status == "failed"
    assert documents.document.processing_error == "OCR 识别失败或服务不可用"
    assert storage.deleted == []
    assert cache.deleted == [document.id]


@pytest.mark.parametrize(
    ("failure_point", "expected_exception", "expects_compensation"),
    [
        ("storage", StorageError, False),
        ("parser", NoExtractableTextError, False),
        ("embedding", EmbeddingError, False),
        ("vectors", VectorStoreError, True),
        ("chunks", StorageError, True),
        ("database", StorageError, True),
    ],
)
def test_failures_mark_document_failed_and_compensate_new_vectors(
    failure_point: str,
    expected_exception: type[Exception],
    expects_compensation: bool,
) -> None:
    document = make_document()
    service, documents, chunks, storage, parser, embedding, vectors, cache, _ = build_service(
        document
    )
    storage.fail_read = failure_point == "storage"
    parser.fail = failure_point == "parser"
    embedding.fail = failure_point == "embedding"
    vectors.fail_upsert = failure_point == "vectors"
    chunks.fail_replace = failure_point == "chunks"
    documents.fail_ready_update = failure_point == "database"

    with pytest.raises(expected_exception):
        service.process(document.id)

    assert documents.document.status == "failed"
    assert documents.document.processing_error is not None
    assert "private" not in documents.document.processing_error
    assert "secret" not in documents.document.processing_error
    assert storage.deleted == []
    assert cache.deleted == [document.id]
    assert bool(vectors.deleted_batches) is expects_compensation
    if expects_compensation:
        assert vectors.deleted_batches[0] == [record.chunk_id for record in vectors.records]


def test_old_vector_cleanup_failure_does_not_change_ready_result() -> None:
    document = make_document(status="ready", version=1, content=b"old")
    old_chunk = make_old_chunk(document)
    service, documents, _, _, _, _, vectors, _, _ = build_service(
        document, b"new content", old_chunks=[old_chunk]
    )
    vectors.fail_old_cleanup = True

    result = service.process(document.id)

    assert result.status == "ready"
    assert documents.document.status == "ready"


def test_list_chunks_filters_current_version_and_page_before_pagination() -> None:
    document = make_document(status="ready", version=2)
    old = make_old_chunk(replace(document, processing_version=1))
    current = replace(
        make_old_chunk(document),
        processing_version=2,
        page_start=2,
        page_end=3,
    )
    other_page = replace(
        make_old_chunk(document),
        processing_version=2,
        page_start=4,
        page_end=4,
    )
    service, _, _, _, _, _, _, _, _ = build_service(
        document,
        old_chunks=[old, current, other_page],
    )

    chunks, total = service.list_chunks(
        document.id,
        offset=0,
        limit=20,
        page_number=2,
    )

    assert chunks == [current]
    assert total == 1
