"""FastAPI 应用入口测试。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from knowledge_assistant.api.dependencies import get_document_service
from knowledge_assistant.api.main import app
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.json_repository import JsonDocumentRepository
from knowledge_assistant.services.document_service import DocumentService

client = TestClient(app)


@pytest.fixture
def document_service(tmp_path: Path) -> Iterator[DocumentService]:
    """通过依赖覆盖为 API 测试提供隔离的文档服务。"""
    repository = JsonDocumentRepository(tmp_path / "data" / "documents.json")
    service = DocumentService(repository, tmp_path / "data" / "uploads")
    app.dependency_overrides[get_document_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


def make_document(document_id: str, name: str) -> Document:
    """创建字段稳定的 API 测试数据。"""
    return Document(
        id=document_id,
        name=name,
        original_path=f"D:\\private\\{name}",
        stored_path=f"D:\\data\\uploads\\{name}",
        file_type=Path(name).suffix,
        file_size=128,
        status="uploaded",
        created_at="2026-08-12T10:00:00+00:00",
    )


def test_health_check() -> None:
    """健康检查应返回稳定的状态和服务信息。"""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "running",
        "service": "knowledge-assistant",
        "version": "0.1.0",
    }


def test_openapi_contains_health_operation() -> None:
    """OpenAPI 文档中应包含健康检查接口。"""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
    assert "/api/v1/documents" in response.json()["paths"]
    assert "/api/v1/documents/{document_id}" in response.json()["paths"]


def test_list_documents_returns_empty_page(document_service: DocumentService) -> None:
    """没有文档时应返回结构完整的空分页。"""
    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 20,
    }


def test_list_documents_paginates_and_hides_internal_paths(
    document_service: DocumentService,
    monkeypatch: MonkeyPatch,
) -> None:
    """列表接口应分页，并通过响应模型过滤服务器内部路径。"""
    documents = [
        make_document("document-1", "first.txt"),
        make_document("document-2", "second.pdf"),
        make_document("document-3", "third.md"),
    ]
    monkeypatch.setattr(
        document_service,
        "list_documents_page",
        lambda offset, limit: (documents[offset : offset + limit], len(documents)),
    )

    response = client.get("/api/v1/documents", params={"offset": 1, "limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert body["items"] == [
        {
            "id": "document-2",
            "name": "second.pdf",
            "file_type": ".pdf",
            "file_size": 128,
            "status": "uploaded",
            "created_at": "2026-08-12T10:00:00+00:00",
        }
    ]
    assert "original_path" not in body["items"][0]
    assert "stored_path" not in body["items"][0]


@pytest.mark.parametrize(
    ("params", "invalid_field"),
    [
        ({"offset": -1}, "offset"),
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
    ],
)
def test_list_documents_rejects_invalid_pagination(
    params: dict[str, int],
    invalid_field: str,
    document_service: DocumentService,
) -> None:
    """分页参数违反边界时应由 FastAPI 返回 422。"""
    response = client.get("/api/v1/documents", params=params)

    assert response.status_code == 422
    assert invalid_field in str(response.json())


def test_get_document_returns_document_and_hides_internal_paths(
    document_service: DocumentService,
    monkeypatch: MonkeyPatch,
) -> None:
    """详情接口应返回指定文档，并过滤服务器内部路径。"""
    document = make_document("document-1", "guide.pdf")
    monkeypatch.setattr(document_service, "get_document", lambda document_id: document)

    response = client.get("/api/v1/documents/document-1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "document-1",
        "name": "guide.pdf",
        "file_type": ".pdf",
        "file_size": 128,
        "status": "uploaded",
        "created_at": "2026-08-12T10:00:00+00:00",
    }
    assert "original_path" not in response.json()
    assert "stored_path" not in response.json()


def test_get_document_returns_404_when_missing(document_service: DocumentService) -> None:
    """详情接口应把领域层的文档不存在异常转换为 HTTP 404。"""
    response = client.get("/api/v1/documents/missing-id")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found: missing-id"}
