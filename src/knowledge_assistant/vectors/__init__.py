"""向量存储抽象及 Milvus 实现。"""

from knowledge_assistant.vectors.base import (
    VectorRecord,
    VectorRepository,
    VectorSearchHit,
)
from knowledge_assistant.vectors.milvus_repository import MilvusVectorRepository

__all__ = [
    "MilvusVectorRepository",
    "VectorRecord",
    "VectorRepository",
    "VectorSearchHit",
]
