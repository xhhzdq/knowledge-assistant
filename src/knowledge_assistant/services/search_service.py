"""基于 Embedding、Milvus 与 PostgreSQL 的语义检索服务。"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from knowledge_assistant.embeddings.base import EmbeddingProvider
from knowledge_assistant.exceptions import DocumentNotFoundError
from knowledge_assistant.models import Document
from knowledge_assistant.processing.models import ChunkSource
from knowledge_assistant.repositories.base import DocumentRepository
from knowledge_assistant.repositories.chunk_repository import DocumentChunkRepository
from knowledge_assistant.vectors.base import VectorRepository, VectorSearchHit


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    """一个通过 PostgreSQL 有效性检查的搜索结果。"""

    rank: int
    score: float
    document_id: str
    document_name: str
    chunk_id: str
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    source_type: ChunkSource


@dataclass(frozen=True, slots=True)
class SemanticSearchResult:
    """语义检索结果及执行摘要。"""

    query: str
    embedding_model: str
    items: list[SearchResultItem]
    returned: int
    duration_ms: int


class SearchService:
    """召回向量候选，并以 PostgreSQL 当前数据作为最终事实来源。"""

    def __init__(
        self,
        documents: DocumentRepository,
        chunks: DocumentChunkRepository,
        embedding: EmbeddingProvider,
        vectors: VectorRepository,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._embedding = embedding
        self._vectors = vectors

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_ids: list[str] | None = None,
        min_score: float | None = None,
    ) -> SemanticSearchResult:
        """执行语义检索，并过滤孤儿、旧版本和未就绪文档。"""
        started_at = monotonic()
        normalized_query = query.strip()
        self._validate(normalized_query, top_k, document_ids, min_score)
        normalized_ids = list(dict.fromkeys(document_ids or [])) or None

        query_vector = self._embedding.embed_query(normalized_query)
        candidates = self._vectors.search(
            query_vector,
            top_k=top_k * 3,
            document_ids=normalized_ids,
        )
        if min_score is not None:
            candidates = [candidate for candidate in candidates if candidate.score >= min_score]

        unique_chunk_ids = list(dict.fromkeys(hit.chunk_id for hit in candidates))
        chunks = self._chunks.get_many_by_ids(unique_chunk_ids)
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        documents_by_id = self._load_documents(candidates)

        items: list[SearchResultItem] = []
        seen_chunk_ids: set[str] = set()
        for candidate in candidates:
            if candidate.chunk_id in seen_chunk_ids:
                continue
            chunk = chunks_by_id.get(candidate.chunk_id)
            document = documents_by_id.get(candidate.document_id)
            if chunk is None or document is None:
                continue
            if chunk.document_id != candidate.document_id:
                continue
            if chunk.processing_version != candidate.processing_version:
                continue
            if document.status != "ready":
                continue
            if document.processing_version != candidate.processing_version:
                continue
            seen_chunk_ids.add(candidate.chunk_id)
            items.append(
                SearchResultItem(
                    rank=len(items) + 1,
                    score=candidate.score,
                    document_id=document.id,
                    document_name=document.name,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    source_type=chunk.source_type,
                )
            )
            if len(items) == top_k:
                break

        return SemanticSearchResult(
            query=normalized_query,
            embedding_model=self._embedding.model_name,
            items=items,
            returned=len(items),
            duration_ms=max(0, round((monotonic() - started_at) * 1000)),
        )

    def _load_documents(self, candidates: list[VectorSearchHit]) -> dict[str, Document]:
        documents: dict[str, Document] = {}
        for document_id in dict.fromkeys(hit.document_id for hit in candidates):
            try:
                documents[document_id] = self._documents.get_by_id(document_id)
            except DocumentNotFoundError:
                # Milvus 异步清理前可能短暂保留孤儿向量，搜索时直接丢弃。
                continue
        return documents

    @staticmethod
    def _validate(
        query: str,
        top_k: int,
        document_ids: list[str] | None,
        min_score: float | None,
    ) -> None:
        if not query or len(query) > 500:
            raise ValueError("query must contain between 1 and 500 characters")
        if top_k < 1 or top_k > 20:
            raise ValueError("top_k must be between 1 and 20")
        if document_ids is not None and len(document_ids) > 50:
            raise ValueError("document_ids must contain at most 50 values")
        for document_id in document_ids or []:
            try:
                UUID(document_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("document_ids must contain valid UUID values") from exc
        if min_score is not None and not -1 <= min_score <= 1:
            raise ValueError("min_score must be between -1 and 1")
