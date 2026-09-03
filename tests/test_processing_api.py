"""文档处理与 Chunk HTTP 契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from knowledge_assistant.api.dependencies import get_document_processing_service
from knowledge_assistant.api.main import app
from knowledge_assistant.exceptions import (
    DocumentNotFoundError,
    DocumentParsingError,
    DocumentProcessingError,
    EmbeddingError,
    NoExtractableTextError,
    OcrError,
    ProcessingInProgressError,
    StorageError,
    UnsupportedDocumentTypeError,
    VectorStoreError,
)
from knowledge_assistant.processing.models import TextChunk
from knowledge_assistant.services.document_processing_service import DocumentProcessingResult

client = TestClient(app)


class FakeProcessingService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.process_args: tuple[str, bool, str] | None = None
        self.list_args: tuple[str, int, int, int | None] | None = None
        self.chunks: list[TextChunk] = []

    def process(self, document_id: str, *, force: bool, ocr_mode: str) -> DocumentProcessingResult:
        self.process_args = (document_id, force, ocr_mode)
        if self.error is not None:
            raise self.error
        return DocumentProcessingResult(
            document_id=document_id,
            status="ready",
            processing_version=2,
            chunk_count=1,
            vector_count=1,
            parser_name="pypdf",
            ocr_page_count=1,
            embedding_model="BAAI/bge-small-zh-v1.5",
            duration_ms=125,
            processed_at="2026-09-03T08:00:00+00:00",
        )

    def list_chunks(
        self,
        document_id: str,
        *,
        offset: int,
        limit: int,
        page_number: int | None,
    ) -> tuple[list[TextChunk], int]:
        self.list_args = (document_id, offset, limit, page_number)
        if self.error is not None:
            raise self.error
        return self.chunks[offset : offset + limit], len(self.chunks)


@pytest.fixture
def service() -> FakeProcessingService:
    fake = FakeProcessingService()
    app.dependency_overrides[get_document_processing_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def make_chunk() -> TextChunk:
    text = "这是公开的 Chunk 正文"
    return TextChunk(
        id=str(uuid4()),
        document_id=str(uuid4()),
        processing_version=2,
        chunk_index=0,
        content=text,
        content_hash="a" * 64,
        char_start=0,
        char_end=len(text),
        page_start=2,
        page_end=3,
        source_type="ocr",
        ocr_confidence=0.95,
        token_count=8,
        created_at=datetime.now(UTC),
    )


def test_process_document_returns_plan_contract_and_forwards_options(
    service: FakeProcessingService,
) -> None:
    response = client.post(
        "/api/v1/documents/document-1/process",
        json={"force": True, "ocr_mode": "force"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": "document-1",
        "status": "ready",
        "processing_version": 2,
        "chunk_count": 1,
        "vector_count": 1,
        "parser_name": "pypdf",
        "ocr_page_count": 1,
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "duration_ms": 125,
        "processed_at": "2026-09-03T08:00:00+00:00",
    }
    assert service.process_args == ("document-1", True, "force")
    body = response.json()
    assert "stored_path" not in body
    assert "embedding" not in body
    assert "reused" not in body


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (DocumentNotFoundError("private id"), 404, "DOCUMENT_NOT_FOUND"),
        (ProcessingInProgressError("private state"), 409, "PROCESSING_IN_PROGRESS"),
        (UnsupportedDocumentTypeError("private suffix"), 415, "UNSUPPORTED_DOCUMENT_TYPE"),
        (NoExtractableTextError("private text"), 422, "NO_EXTRACTABLE_TEXT"),
        (StorageError("secret endpoint"), 503, "PROCESSING_DEPENDENCY_UNAVAILABLE"),
        (OcrError("secret model"), 503, "PROCESSING_DEPENDENCY_UNAVAILABLE"),
        (EmbeddingError("secret path"), 503, "PROCESSING_DEPENDENCY_UNAVAILABLE"),
        (VectorStoreError("secret host"), 503, "PROCESSING_DEPENDENCY_UNAVAILABLE"),
        (DocumentParsingError("private parser"), 500, "PROCESSING_FAILED"),
        (DocumentProcessingError("private stack"), 500, "PROCESSING_FAILED"),
        (RuntimeError("unexpected stack"), 500, "PROCESSING_FAILED"),
    ],
)
def test_process_document_maps_errors_without_exposing_details(
    service: FakeProcessingService,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    service.error = error

    response = client.post("/api/v1/documents/document-1/process", json={})

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "private" not in response.text
    assert "secret" not in response.text
    assert "stack" not in response.text


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"ocr_mode": "sometimes"}, "ocr_mode"),
        ({"force": "not-a-boolean"}, "force"),
    ],
)
def test_process_document_rejects_invalid_body(
    service: FakeProcessingService,
    payload: dict[str, object],
    field: str,
) -> None:
    response = client.post("/api/v1/documents/document-1/process", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in response.json()["error"]["message"]
    assert service.process_args is None


def test_list_chunks_returns_public_fields_and_forwards_page_filter(
    service: FakeProcessingService,
) -> None:
    chunk = make_chunk()
    service.chunks = [chunk]

    response = client.get(
        f"/api/v1/documents/{chunk.document_id}/chunks",
        params={"offset": 0, "limit": 10, "page_number": 2},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "processing_version": 2,
                "chunk_index": 0,
                "content": chunk.content,
                "page_start": 2,
                "page_end": 3,
                "source_type": "ocr",
                "ocr_confidence": 0.95,
                "token_count": 8,
            }
        ],
        "total": 1,
        "offset": 0,
        "limit": 10,
    }
    assert service.list_args == (chunk.document_id, 0, 10, 2)
    assert "content_hash" not in response.text
    assert "embedding" not in response.text


def test_list_chunks_returns_empty_page_for_unprocessed_document(
    service: FakeProcessingService,
) -> None:
    response = client.get("/api/v1/documents/document-1/chunks")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 20}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"offset": -1}, "offset"),
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"page_number": 0}, "page_number"),
    ],
)
def test_list_chunks_rejects_invalid_query(
    service: FakeProcessingService,
    params: dict[str, int],
    field: str,
) -> None:
    response = client.get("/api/v1/documents/document-1/chunks", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in response.json()["error"]["message"]
    assert service.list_args is None


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (DocumentNotFoundError("private id"), 404, "DOCUMENT_NOT_FOUND"),
        (StorageError("secret database"), 503, "PROCESSING_DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_list_chunks_maps_repository_errors(
    service: FakeProcessingService,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    service.error = error

    response = client.get("/api/v1/documents/document-1/chunks")

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "private" not in response.text
    assert "secret" not in response.text


def test_openapi_describes_synchronous_processing_and_ocr_modes(
    service: FakeProcessingService,
) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/documents/{document_id}/process"]["post"]
    request_schema = schema["components"]["schemas"]["DocumentProcessRequest"]

    assert "同步" in operation["description"]
    assert "ocr_mode" in operation["description"]
    assert request_schema["properties"]["ocr_mode"]["enum"] == ["auto", "never", "force"]
