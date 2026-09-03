"""语义检索 HTTP API。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from knowledge_assistant.api.dependencies import get_search_service
from knowledge_assistant.exceptions import EmbeddingError, StorageError, VectorStoreError
from knowledge_assistant.schemas.documents import ErrorDetail, ErrorResponse
from knowledge_assistant.schemas.search import SemanticSearchRequest, SemanticSearchResponse
from knowledge_assistant.services.search_service import SearchService

router = APIRouter(prefix="/api/v1", tags=["search"])
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "查询参数无效",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Embedding、Milvus 或 PostgreSQL 暂时不可用",
    },
}


def _error(code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=503, content=body.model_dump())


@router.post("/search", response_model=SemanticSearchResponse, responses=ERROR_RESPONSES)
def semantic_search(
    payload: SemanticSearchRequest,
    service: SearchServiceDependency,
) -> SemanticSearchResponse | JSONResponse:
    """向量召回后回查 PostgreSQL，只返回当前有效 Chunk。"""
    try:
        result = service.search(
            payload.query,
            top_k=payload.top_k,
            document_ids=(
                [str(document_id) for document_id in payload.document_ids]
                if payload.document_ids is not None
                else None
            ),
            min_score=payload.min_score,
        )
    except EmbeddingError:
        return _error("EMBEDDING_UNAVAILABLE", "Embedding model is unavailable")
    except VectorStoreError:
        return _error("VECTOR_STORE_UNAVAILABLE", "Vector store is unavailable")
    except StorageError:
        return _error("SEARCH_DEPENDENCY_UNAVAILABLE", "Search dependency is unavailable")
    return SemanticSearchResponse.model_validate(result)
