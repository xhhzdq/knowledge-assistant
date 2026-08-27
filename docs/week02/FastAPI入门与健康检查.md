# FastAPI 入门与健康检查

## 1. 本阶段范围

提前进入第二周的第一小步，只完成 FastAPI 应用入口和 `/health` 接口。暂不接入 SQLAlchemy、PostgreSQL 或已有文档 Service。

## 2. FastAPI 应用实例

```python
app = FastAPI(
    title="Knowledge Assistant API",
    version="0.1.0",
)
```

`app` 是 FastAPI 类的实例，也是 ASGI 服务器加载应用时使用的入口。

## 3. 路径操作装饰器

```python
@app.get("/health")
def health_check():
    ...
```

`@app.get("/health")` 将下面的函数注册为 HTTP GET `/health` 的处理函数。收到匹配请求时，FastAPI 调用该函数并将返回值序列化为 JSON。

## 4. Pydantic 响应模型

`HealthResponse` 继承 Pydantic 的 `BaseModel`，用于定义和校验 HTTP 响应结构。它与内部领域模型 `Document` 的 dataclass 职责不同：Pydantic 主要服务于 API 边界的数据校验和 OpenAPI 文档。

## 5. 启动方式

```powershell
uvicorn knowledge_assistant.api.main:app --reload
```

其中：

```text
knowledge_assistant.api.main  → Python 模块
app                           → 模块中的 FastAPI 实例
--reload                      → 开发时监控代码变更并自动重启
```

启动后访问：

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 6. 测试原理

FastAPI 的 `TestClient` 在测试进程中向 ASGI 应用发送模拟 HTTP 请求，不需要真正监听 8000 端口。测试验证 `/health` 的状态码、JSON 内容，以及 OpenAPI 中是否注册该路径。

当前 FastAPI/Starlette 版本的 TestClient 优先使用 `httpx2`，因此将它作为开发依赖，避免继续使用兼容层中的旧 `httpx` 弃用路径。
