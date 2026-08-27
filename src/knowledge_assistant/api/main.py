"""FastAPI 应用入口。"""

from fastapi import FastAPI
from pydantic import BaseModel

from knowledge_assistant.api.routes.documents import router as documents_router


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


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """返回应用进程的基础健康状态。"""
    return HealthResponse(
        status="running",
        service="knowledge-assistant",
        version=app.version,
    )
