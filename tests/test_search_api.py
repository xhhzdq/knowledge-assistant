"""语义检索 API 契约测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from knowledge_assistant.api.dependencies import get_search_service
from knowledge_assistant.api.main import app
from knowledge_assistant.exceptions import EmbeddingError, StorageError, VectorStoreError
from knowledge_assistant.services.search_service import (
    SearchResultItem,
    SemanticSearchResult,
)

client = TestClient(app)


class FakeSearchService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.arguments: tuple[str, int, list[str] | None, float | None] | None = None

    def search(
        self,
        query: str,
        *,
        top_k: int,
        document_ids: list[str] | None,
        min_score: float | None,
    ) -> SemanticSearchResult:
        self.arguments = (query, top_k, document_ids, min_score)
        if self.error is not None:
            raise self.error
        document_id = document_ids[0] if document_ids else str(uuid4())
        return SemanticSearchResult(
            query=query,
            embedding_model="BAAI/bge-small-zh-v1.5",
            items=[
                SearchResultItem(
                    rank=1,
                    score=0.86,
                    document_id=document_id,
                    document_name="Alembic学习文档.md",
                    chunk_id=str(uuid4()),
                    chunk_index=3,
                    content="迁移由 alembic upgrade head 触发。",
                    page_start=None,
                    page_end=None,
                    source_type="parser",
                )
            ],
            returned=1,
            duration_ms=48,
        )


@pytest.fixture
def service() -> FakeSearchService:
    fake = FakeSearchService()
    app.dependency_overrides[get_search_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_search_returns_public_contract_and_forwards_filters(service: FakeSearchService) -> None:
    document_id = str(uuid4())
    response = client.post(
        "/api/v1/search",
        json={
            "query": "  数据库迁移如何触发？  ",
            "top_k": 3,
            "document_ids": [document_id],
            "min_score": 0.5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "数据库迁移如何触发？"
    assert body["embedding_model"] == "BAAI/bge-small-zh-v1.5"
    assert body["returned"] == 1
    assert body["items"][0] == {
        "rank": 1,
        "score": 0.86,
        "document_id": document_id,
        "document_name": "Alembic学习文档.md",
        "chunk_id": body["items"][0]["chunk_id"],
        "chunk_index": 3,
        "content": "迁移由 alembic upgrade head 触发。",
        "page_start": None,
        "page_end": None,
        "source_type": "parser",
    }
    assert service.arguments == ("数据库迁移如何触发？", 3, [document_id], 0.5)
    assert "embedding" not in body["items"][0]
    assert "stored_path" not in response.text


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"query": "   "}, "query"),
        ({"query": "x" * 501}, "query"),
        ({"query": "q", "top_k": 0}, "top_k"),
        ({"query": "q", "top_k": 21}, "top_k"),
        ({"query": "q", "document_ids": ["invalid"]}, "document_ids"),
        ({"query": "q", "document_ids": [str(uuid4())] * 51}, "document_ids"),
        ({"query": "q", "min_score": -1.1}, "min_score"),
        ({"query": "q", "min_score": 1.1}, "min_score"),
    ],
)
def test_search_rejects_invalid_parameters(
    service: FakeSearchService,
    payload: dict[str, object],
    field: str,
) -> None:
    response = client.post("/api/v1/search", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in response.json()["error"]["message"]
    assert service.arguments is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (EmbeddingError("private model path"), "EMBEDDING_UNAVAILABLE"),
        (VectorStoreError("private host"), "VECTOR_STORE_UNAVAILABLE"),
        (StorageError("private database"), "SEARCH_DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_search_maps_dependency_errors_without_leaking_details(
    service: FakeSearchService,
    error: Exception,
    code: str,
) -> None:
    service.error = error

    response = client.post("/api/v1/search", json={"query": "query"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text
