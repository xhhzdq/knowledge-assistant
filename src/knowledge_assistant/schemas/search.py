"""语义检索 API 的请求与响应模型。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SemanticSearchRequest(BaseModel):
    """语义搜索参数。"""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[UUID] | None = Field(default=None, max_length=50)
    min_score: float | None = Field(default=None, ge=-1, le=1)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        """在长度校验前去除查询首尾空白。"""
        return value.strip() if isinstance(value, str) else value


class SearchResultItemResponse(BaseModel):
    """一个语义召回结果。"""

    model_config = ConfigDict(from_attributes=True)

    rank: int = Field(ge=1)
    score: float = Field(ge=-1, le=1)
    document_id: str
    document_name: str
    chunk_id: str
    chunk_index: int = Field(ge=0)
    content: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    source_type: Literal["parser", "ocr", "mixed"]


class SemanticSearchResponse(BaseModel):
    """语义搜索响应。"""

    model_config = ConfigDict(from_attributes=True)

    query: str
    embedding_model: str
    items: list[SearchResultItemResponse]
    returned: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
