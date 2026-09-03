"""SearchService 语义召回与事实来源过滤测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from knowledge_assistant.exceptions import (
    DocumentNotFoundError,
    EmbeddingError,
    VectorStoreError,
)
from knowledge_assistant.models import Document
from knowledge_assistant.processing.models import TextChunk
from knowledge_assistant.services.search_service import SearchService
from knowledge_assistant.vectors.base import VectorSearchHit


def make_document(*, status: str = "ready", version: int = 2) -> Document:
    now = datetime.now(UTC).isoformat()
    return Document(
        id=str(uuid4()),
        name="知识库.md",
        original_path="private/source.md",
        stored_path="documents/private.md",
        file_type=".md",
        file_size=100,
        status=status,
        created_at=now,
        updated_at=now,
        processing_version=version,
        content_hash="a" * 64,
        processed_at=now,
    )


def make_chunk(document: Document, index: int = 0, *, version: int | None = None) -> TextChunk:
    content = f"chunk-{index} 正文"
    return TextChunk(
        id=str(uuid4()),
        document_id=document.id,
        processing_version=version or document.processing_version,
        chunk_index=index,
        content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        char_start=index * 20,
        char_end=index * 20 + len(content),
        page_start=index + 1,
        page_end=index + 1,
        source_type="parser",
        ocr_confidence=None,
        token_count=3,
        created_at=datetime.now(UTC),
    )


class FakeDocuments:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = {document.id: document for document in documents}

    def get_by_id(self, document_id: str) -> Document:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise DocumentNotFoundError(document_id) from exc


class FakeChunks:
    def __init__(self, chunks: list[TextChunk]) -> None:
        self.chunks = {chunk.id: chunk for chunk in chunks}
        self.requested_ids: list[str] = []

    def get_many_by_ids(self, chunk_ids: list[str]) -> list[TextChunk]:
        self.requested_ids = chunk_ids
        return [self.chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self.chunks]


class FakeEmbedding:
    model_name = "fake-bge"
    dimension = 2

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.error: Exception | None = None

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def count_tokens(self, text: str) -> int:
        return 1


class FakeVectors:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[list[float], int, list[str] | None]] = []
        self.error: Exception | None = None

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[VectorSearchHit]:
        self.calls.append((query_vector, top_k, document_ids))
        if self.error is not None:
            raise self.error
        return self.hits[:top_k]


def hit(chunk: TextChunk, score: float = 0.9, *, version: int | None = None) -> VectorSearchHit:
    return VectorSearchHit(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        processing_version=version or chunk.processing_version,
        page_start=chunk.page_start,
        score=score,
    )


def test_search_filters_stale_or_missing_data_and_preserves_milvus_order() -> None:
    ready = make_document()
    not_ready = make_document(status="processing")
    first = make_chunk(ready, 0)
    second = make_chunk(ready, 1)
    stale = make_chunk(ready, 2, version=1)
    blocked = make_chunk(not_ready, 0)
    missing = replace(make_chunk(ready, 3), id=str(uuid4()))
    hits = [
        hit(first, 0.96),
        hit(stale, 0.94),
        hit(blocked, 0.92),
        hit(missing, 0.91),
        hit(second, 0.88),
        hit(first, 0.87),
    ]
    documents = FakeDocuments([ready, not_ready])
    chunks = FakeChunks([first, second, stale, blocked])
    embedding = FakeEmbedding()
    vectors = FakeVectors(hits)
    service = SearchService(documents, chunks, embedding, vectors)

    result = service.search("  如何迁移数据库？  ", top_k=2)

    assert result.query == "如何迁移数据库？"
    assert result.returned == 2
    assert [item.chunk_id for item in result.items] == [first.id, second.id]
    assert [item.rank for item in result.items] == [1, 2]
    assert result.items[0].document_name == ready.name
    assert embedding.queries == ["如何迁移数据库？"]
    assert vectors.calls == [([1.0, 0.0], 6, None)]
    assert chunks.requested_ids == [
        first.id,
        stale.id,
        blocked.id,
        missing.id,
        second.id,
    ]


def test_search_applies_document_ids_and_min_score() -> None:
    document = make_document()
    first = make_chunk(document, 0)
    second = make_chunk(document, 1)
    vectors = FakeVectors([hit(first, 0.8), hit(second, 0.49)])
    service = SearchService(
        FakeDocuments([document]),
        FakeChunks([first, second]),
        FakeEmbedding(),
        vectors,
    )

    result = service.search(
        "query",
        top_k=5,
        document_ids=[document.id, document.id],
        min_score=0.5,
    )

    assert [item.chunk_id for item in result.items] == [first.id]
    assert vectors.calls[0][1:] == (15, [document.id])


@pytest.mark.parametrize(
    ("query", "top_k", "document_ids", "min_score"),
    [
        ("   ", 5, None, None),
        ("x" * 501, 5, None, None),
        ("query", 0, None, None),
        ("query", 21, None, None),
        ("query", 5, ["not-a-uuid"], None),
        ("query", 5, [str(uuid4())] * 51, None),
        ("query", 5, None, -1.1),
        ("query", 5, None, 1.1),
    ],
)
def test_search_rejects_invalid_arguments(
    query: str,
    top_k: int,
    document_ids: list[str] | None,
    min_score: float | None,
) -> None:
    embedding = FakeEmbedding()
    vectors = FakeVectors([])
    service = SearchService(FakeDocuments([]), FakeChunks([]), embedding, vectors)

    with pytest.raises(ValueError):
        service.search(
            query,
            top_k=top_k,
            document_ids=document_ids,
            min_score=min_score,
        )

    assert embedding.queries == []
    assert vectors.calls == []


@pytest.mark.parametrize("error", [EmbeddingError("model"), VectorStoreError("milvus")])
def test_search_propagates_embedding_and_vector_failures(error: Exception) -> None:
    embedding = FakeEmbedding()
    vectors = FakeVectors([])
    if isinstance(error, EmbeddingError):
        embedding.error = error
    else:
        vectors.error = error
    service = SearchService(FakeDocuments([]), FakeChunks([]), embedding, vectors)

    with pytest.raises(type(error)):
        service.search("query")
