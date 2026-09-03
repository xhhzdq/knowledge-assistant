"""文档处理与 Chunk 查询 API 的数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentProcessRequest(BaseModel):
    """同步处理文档时允许客户端指定的选项。"""

    force: bool = Field(default=False, description="是否忽略幂等判断并强制创建新版本")
    ocr_mode: Literal["auto", "never", "force"] = Field(
        default="auto",
        description="OCR 策略：自动识别、禁止识别或强制识别",
    )


class DocumentProcessResponse(BaseModel):
    """一次同步处理或幂等命中的摘要。"""

    model_config = ConfigDict(from_attributes=True)

    document_id: str
    status: Literal["ready"]
    processing_version: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    vector_count: int = Field(ge=1)
    parser_name: str
    ocr_page_count: int = Field(ge=0)
    embedding_model: str
    duration_ms: int = Field(ge=0)
    processed_at: str


class ChunkResponse(BaseModel):
    """可向客户端公开的 Chunk 字段，不包含内容指纹等内部数据。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    processing_version: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    content: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    source_type: Literal["parser", "ocr", "mixed"]
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    token_count: int = Field(ge=1)


class ChunkListResponse(BaseModel):
    """Chunk 分页响应。"""

    items: list[ChunkResponse]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
