"""文档同步处理与 Chunk 查询 API。"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse

from knowledge_assistant.api.dependencies import get_document_processing_service
from knowledge_assistant.exceptions import (
    DocumentNotFoundError,
    DocumentParsingError,
    DocumentProcessingError,
    EmbeddingError,
    KnowledgeAssistantError,
    NoExtractableTextError,
    OcrError,
    ProcessingInProgressError,
    StorageError,
    UnsupportedDocumentTypeError,
    VectorStoreError,
)
from knowledge_assistant.schemas.documents import ErrorDetail, ErrorResponse
from knowledge_assistant.schemas.processing import (
    ChunkListResponse,
    ChunkResponse,
    DocumentProcessRequest,
    DocumentProcessResponse,
)
from knowledge_assistant.services.document_processing_service import DocumentProcessingService

router = APIRouter(prefix="/api/v1/documents", tags=["document-processing"])
logger = logging.getLogger(__name__)

ProcessingServiceDependency = Annotated[
    DocumentProcessingService,
    Depends(get_document_processing_service),
]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "文档不存在"},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "文档正在处理"},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
        "model": ErrorResponse,
        "description": "不支持的文档类型",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "文档没有可提取文本或请求参数无效",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "处理依赖暂时不可用",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "文档处理失败",
    },
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """用统一 ErrorResponse 构造安全的错误响应。"""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


@router.post(
    "/{document_id}/process",
    response_model=DocumentProcessResponse,
    responses=ERROR_RESPONSES,
    summary="同步处理文档",
    description=(
        "同步执行原文件读取、解析、按需 OCR、分块、向量化和持久化。"
        "请求会等待整个流程结束；ocr_mode 支持 auto、never 和 force。"
    ),
)
def process_document(
    document_id: Annotated[str, Path(min_length=1, description="文档唯一 ID")],
    payload: DocumentProcessRequest,
    service: ProcessingServiceDependency,
) -> DocumentProcessResponse | JSONResponse:
    """执行处理服务，并把领域异常映射成稳定的 HTTP 契约。"""
    try:
        result = service.process(
            document_id,
            force=payload.force,
            ocr_mode=payload.ocr_mode,
        )
    except DocumentNotFoundError:
        return _error(404, "DOCUMENT_NOT_FOUND", "Document not found")
    except ProcessingInProgressError:
        return _error(409, "PROCESSING_IN_PROGRESS", "Document processing is in progress")
    except UnsupportedDocumentTypeError:
        return _error(415, "UNSUPPORTED_DOCUMENT_TYPE", "Unsupported document type")
    except NoExtractableTextError:
        return _error(422, "NO_EXTRACTABLE_TEXT", "Document contains no extractable text")
    except (StorageError, OcrError, EmbeddingError, VectorStoreError):
        return _error(
            503,
            "PROCESSING_DEPENDENCY_UNAVAILABLE",
            "A processing dependency is unavailable",
        )
    except (DocumentParsingError, DocumentProcessingError, KnowledgeAssistantError):
        return _error(500, "PROCESSING_FAILED", "Document processing failed")
    except Exception:
        logger.exception("处理 API 捕获未分类异常: document_id=%s", document_id)
        return _error(500, "PROCESSING_FAILED", "Document processing failed")
    return DocumentProcessResponse.model_validate(result)


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkListResponse,
    responses={404: {"model": ErrorResponse, "description": "文档不存在"}},
    summary="分页查询当前版本的 Chunk",
)
def list_document_chunks(
    document_id: Annotated[str, Path(min_length=1, description="文档唯一 ID")],
    service: ProcessingServiceDependency,
    offset: Annotated[int, Query(ge=0, description="跳过的 Chunk 数量")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="最多返回的 Chunk 数量")] = 20,
    page_number: Annotated[
        int | None,
        Query(ge=1, description="只返回页码范围覆盖该页的 Chunk"),
    ] = None,
) -> ChunkListResponse | JSONResponse:
    """查询当前 processing_version；尚未处理时返回空页。"""
    try:
        chunks, total = service.list_chunks(
            document_id,
            offset=offset,
            limit=limit,
            page_number=page_number,
        )
    except DocumentNotFoundError:
        return _error(404, "DOCUMENT_NOT_FOUND", "Document not found")
    except StorageError:
        return _error(
            503,
            "PROCESSING_DEPENDENCY_UNAVAILABLE",
            "A processing dependency is unavailable",
        )
    return ChunkListResponse(
        items=[ChunkResponse.model_validate(chunk) for chunk in chunks],
        total=total,
        offset=offset,
        limit=limit,
    )
