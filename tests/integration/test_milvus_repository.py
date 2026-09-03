"""连接真实 Milvus 的向量仓储集成测试。"""

import math
from uuid import uuid4

import pytest
from pymilvus import MilvusClient

from knowledge_assistant.core.config import MilvusSettings
from knowledge_assistant.vectors import MilvusVectorRepository, VectorRecord

DIMENSION = 512


def normalized_vector(first: float, second: float) -> list[float]:
    """生成维度固定的单位向量，便于断言 COSINE 排序。"""
    norm = math.sqrt(first * first + second * second)
    return [first / norm, second / norm, *([0.0] * (DIMENSION - 2))]


@pytest.mark.integration
def test_real_milvus_upsert_search_filter_and_delete() -> None:
    settings = MilvusSettings()
    collection_name = f"test_document_chunks_{uuid4().hex}"
    raw_client = MilvusClient(
        uri=str(settings.milvus_uri),
        timeout=settings.milvus_timeout_seconds,
    )
    repository = MilvusVectorRepository(
        str(settings.milvus_uri),
        collection_name=collection_name,
        dimension=DIMENSION,
        metric_type="COSINE",
        timeout_seconds=settings.milvus_timeout_seconds,
        client=raw_client,  # type: ignore[arg-type]
    )
    first_document_id = str(uuid4())
    second_document_id = str(uuid4())
    first_chunk_id = str(uuid4())
    second_chunk_id = str(uuid4())
    third_chunk_id = str(uuid4())

    first = VectorRecord(
        first_chunk_id,
        first_document_id,
        1,
        1,
        normalized_vector(1.0, 0.0),
    )
    replacement = VectorRecord(
        first_chunk_id,
        first_document_id,
        2,
        2,
        normalized_vector(1.0, 0.05),
    )
    second = VectorRecord(
        second_chunk_id,
        first_document_id,
        2,
        3,
        normalized_vector(0.8, 0.6),
    )
    third = VectorRecord(
        third_chunk_id,
        second_document_id,
        1,
        None,
        normalized_vector(0.0, 1.0),
    )

    try:
        repository.upsert([first])
        repository.upsert([replacement, second, third])

        hits = repository.search(normalized_vector(1.0, 0.0), top_k=10)
        assert [hit.chunk_id for hit in hits] == [
            first_chunk_id,
            second_chunk_id,
            third_chunk_id,
        ]
        assert hits[0].processing_version == 2
        assert hits[0].page_start == 2

        filtered = repository.search(
            normalized_vector(1.0, 0.0),
            top_k=10,
            document_ids=[second_document_id],
        )
        assert [hit.chunk_id for hit in filtered] == [third_chunk_id]

        assert repository.delete_by_chunk_ids([second_chunk_id]) == 1
        assert repository.delete_by_document_id(first_document_id) == 1
        remaining = repository.search(normalized_vector(1.0, 0.0), top_k=10)
        assert [hit.chunk_id for hit in remaining] == [third_chunk_id]
    finally:
        if raw_client.has_collection(collection_name):
            raw_client.drop_collection(collection_name)
