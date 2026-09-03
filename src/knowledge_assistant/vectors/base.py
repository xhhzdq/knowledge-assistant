"""向量仓储的领域模型与抽象接口。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from knowledge_assistant.embeddings.base import EmbeddingVector


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """一个 Chunk 写入向量库时需要的最小数据。"""

    chunk_id: str
    document_id: str
    processing_version: int
    page_start: int | None
    embedding: EmbeddingVector


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    """Milvus 召回的一条向量命中，不在向量库重复保存正文。"""

    chunk_id: str
    document_id: str
    processing_version: int
    page_start: int | None
    score: float


class VectorRepository(Protocol):
    """处理服务与搜索服务共同依赖的向量存储能力。"""

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        """按 ``chunk_id`` 幂等新增或替换一批向量。"""
        ...

    def search(
        self,
        query_vector: Sequence[float],
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> list[VectorSearchHit]:
        """按 COSINE 相似度搜索，并可限定文档范围。"""
        ...

    def delete_by_document_id(self, document_id: str) -> int:
        """删除一个文档的全部向量并返回删除数量。"""
        ...

    def delete_by_chunk_ids(self, chunk_ids: Sequence[str]) -> int:
        """按 Chunk 主键批量删除并返回删除数量。"""
        ...
