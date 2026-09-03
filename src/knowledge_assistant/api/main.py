"""FastAPI 应用入口。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from knowledge_assistant.api.routes.documents import router as documents_router
from knowledge_assistant.api.routes.processing import router as processing_router
from knowledge_assistant.api.routes.search import router as search_router
from knowledge_assistant.schemas.documents import ErrorDetail, ErrorResponse


class HealthResponse(BaseModel):
    """健康检查接口的响应结构。"""

    status: str
    service: str
    version: str


app = FastAPI(
    title="Knowledge Assistant API",
    description="企业文档智能问答系统学习项目 API。",
    version="0.1.0",
)

# 主应用只负责组装路由，各业务接口放在独立的 Router 中。
app.include_router(documents_router)
app.include_router(processing_router)
app.include_router(search_router)


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 FastAPI 参数校验错误转换成统一、安全的错误结构。"""
    fields: set[str] = set()
    for error in exc.errors():
        location = error.get("loc", ())
        if location and location[0] in {"body", "path", "query", "header"}:
            location = location[1:]
        field = next(
            (
                part
                for part in location
                if isinstance(part, str)
            ),
            None,
        )
        if field is not None:
            fields.add(field)
    sorted_fields = sorted(fields)
    suffix = f": {', '.join(sorted_fields)}" if sorted_fields else ""
    body = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message=f"Request validation failed{suffix}",
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """返回应用进程的基础健康状态。"""
    return HealthResponse(
        status="running",
        service="knowledge-assistant",
        version=app.version,
    )
