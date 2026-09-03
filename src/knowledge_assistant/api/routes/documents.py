"""文档上传、查询、更新和删除 API。"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)

from knowledge_assistant.api.dependencies import get_document_service
from knowledge_assistant.exceptions import (
    DocumentConflictError,
    DocumentNotFoundError,
    InvalidDocumentError,
    StorageError,
)
from knowledge_assistant.schemas.documents import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdateRequest,
)
from knowledge_assistant.services.document_service import DocumentService

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

DocumentServiceDependency = Annotated[DocumentService, Depends(get_document_service)]


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "文件名、类型或大小不符合要求"},
        status.HTTP_409_CONFLICT: {"description": "文档数据冲突"},
    },
)
def upload_document(
    file: Annotated[UploadFile, File(description="待上传的 txt、md 或 pdf 文件")],
    service: DocumentServiceDependency,
) -> DocumentResponse:
    """接收 multipart 文件，由 Service 保存文件和 PostgreSQL 元数据。"""
    try:
        document = service.add_uploaded_document(file.filename or "", file.file)
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DocumentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to store document",
        ) from exc

    return DocumentResponse.model_validate(document)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    service: DocumentServiceDependency,
    offset: Annotated[int, Query(ge=0, description="跳过的文档数量")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="本次最多返回的文档数量")] = 20,
) -> DocumentListResponse:
    """由 PostgreSQL 完成分页，并返回文档总数。"""
    page, total = service.list_documents_page(offset, limit)

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(document) for document in page],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "文档不存在"}},
)
def get_document(
    document_id: Annotated[str, Path(min_length=1, description="文档唯一 ID")],
    service: DocumentServiceDependency,
) -> DocumentResponse:
    """按 ID 查询文档详情，并将领域异常转换为 HTTP 404。"""
    try:
        document = service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return DocumentResponse.model_validate(document)


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "名称参数无效"},
        status.HTTP_404_NOT_FOUND: {"description": "文档不存在"},
    },
)
def update_document(
    document_id: Annotated[str, Path(min_length=1, description="文档唯一 ID")],
    payload: DocumentUpdateRequest,
    service: DocumentServiceDependency,
) -> DocumentResponse:
    """只更新文档名称；文档状态只能由处理服务维护。"""
    try:
        document = service.update_document(
            document_id,
            name=payload.name,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return DocumentResponse.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={status.HTTP_404_NOT_FOUND: {"description": "文档不存在"}},
)
def delete_document(
    document_id: Annotated[str, Path(min_length=1, description="文档唯一 ID")],
    service: DocumentServiceDependency,
) -> Response:
    """删除 PostgreSQL 元数据和服务器保存的文件副本。"""
    try:
        service.delete_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete document",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
