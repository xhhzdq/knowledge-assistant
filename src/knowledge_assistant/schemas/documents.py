"""文档 API 使用的 Pydantic Schema。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentResponse(BaseModel):
    """对客户端公开的文档元数据。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="文档唯一 ID")
    name: str = Field(description="文件名称")
    file_type: str = Field(description="小写文件扩展名")
    file_size: int = Field(ge=0, description="文件大小，单位为字节")
    status: str = Field(description="文档处理状态")
    created_at: str = Field(description="ISO 8601 格式的 UTC 创建时间")
    updated_at: str = Field(description="ISO 8601 格式的 UTC 更新时间")
    processing_version: int = Field(ge=0, description="当前文档处理版本")
    processed_at: str | None = Field(default=None, description="最近处理成功时间")
    processing_error: str | None = Field(default=None, description="安全的处理失败摘要")


class DocumentListResponse(BaseModel):
    """文档分页列表响应。"""

    items: list[DocumentResponse]
    total: int = Field(ge=0, description="符合条件的文档总数")
    offset: int = Field(ge=0, description="本次查询跳过的文档数量")
    limit: int = Field(ge=1, le=100, description="本次最多返回的文档数量")


class DocumentUpdateRequest(BaseModel):
    """PATCH 接口允许客户端修改的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal["uploaded", "processing", "ready", "failed"] | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "DocumentUpdateRequest":
        """拒绝没有提供任何可更新字段的空请求。"""
        if self.name is None and self.status is None:
            raise ValueError("At least one update field is required")
        return self


class ErrorDetail(BaseModel):
    """统一错误中的详细信息。"""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """后续 API 统一使用的错误响应外层结构。"""

    error: ErrorDetail
