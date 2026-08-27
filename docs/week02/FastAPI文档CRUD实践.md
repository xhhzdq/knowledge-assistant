# FastAPI 文档 CRUD API 集成实践

## 1. 本阶段目标与当前状态

阶段 6 将前面分开学习的组件串成真实 HTTP 调用链：

```text
HTTP 客户端
→ FastAPI Router
→ Pydantic/FastAPI 参数校验
→ DocumentService
→ SqlAlchemyDocumentRepository
→ SQLAlchemy Session
→ PostgreSQL
```

文件本体和元数据仍然分开保存：

```text
文件内容   → data/uploads
文档元数据 → PostgreSQL documents
```

当前接口状态：

| 方法 | 路径 | 状态 | 成功状态码 |
| --- | --- | --- | ---: |
| `POST` | `/api/v1/documents` | 已完成 | 201 |
| `GET` | `/api/v1/documents` | 已完成 | 200 |
| `GET` | `/api/v1/documents/{id}` | 已完成 | 200 |
| `PATCH` | `/api/v1/documents/{id}` | 留给学习者实现 | 当前 501，完成后 200 |
| `DELETE` | `/api/v1/documents/{id}` | 已完成 | 204 |

CLI 没有切换数据库：

```text
CLI → JsonDocumentRepository → data/documents.json
API → SqlAlchemyDocumentRepository → PostgreSQL
```

所以现阶段 CLI 和 API 的元数据互不相通，但 CLI 仍可以正常演示第一周成果。

---

## 2. 新增依赖 `python-multipart`

上传接口使用 `multipart/form-data`，FastAPI 需要 `python-multipart` 解析表单边界、字段和文件内容：

```toml
"python-multipart>=0.0.20"
```

JSON 请求和 multipart 请求不同：

```text
application/json
→ 适合结构化请求体

multipart/form-data
→ 一个请求中传文件和普通表单字段
```

浏览器不能把本机 `D:\资料\guide.pdf` 路径交给服务器读取。它必须把文件字节上传给服务器。

---

## 3. API 如何获得数据库 Service

`api/dependencies.py` 负责组装数据库版 Service。

### 3.1 Engine 生命周期

```python
@lru_cache
def get_engine() -> Engine:
    return create_default_engine()
```

一个 API 进程复用一个 Engine和它的连接池，而不是每个请求重新创建连接池。

### 3.2 Session 生命周期

```python
def get_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
```

每个请求获得一个独立 Session：

```text
请求开始
→ 创建 Session
→ Repository 使用 Session
→ 请求成功或失败
→ 关闭 Session
→ 数据库连接归还连接池
```

### 3.3 Service 组装

```python
repository = SqlAlchemyDocumentRepository(session)
return DocumentService(repository, settings.uploads_dir)
```

Router 只声明：

```python
service: DocumentServiceDependency
```

FastAPI 根据 `Depends` 自动执行上述依赖链。

---

## 4. POST 上传接口

请求：

```http
POST /api/v1/documents
Content-Type: multipart/form-data
```

路由接收：

```python
file: UploadFile
```

`UploadFile` 提供：

- `filename`：客户端提供的文件名。
- `content_type`：客户端声明的 MIME 类型，不应作为唯一安全依据。
- `file`：可读取的临时文件对象。

Router 不直接写文件，而是调用：

```python
service.add_uploaded_document(file.filename, file.file)
```

Service 完成：

```text
清理文件名
→ 检查扩展名
→ 分块复制并统计大小
→ 超限立即失败
→ 生成 Document
→ Repository 写入 PostgreSQL
→ 返回领域对象
```

当前允许：

```text
.txt、.md、.pdf
```

当前最大文件：

```text
10 MiB
```

这里只按扩展名做第一层校验。生产环境还应考虑 MIME 检测、文件签名、恶意内容扫描、PDF 解析限制和租户配额。

### 数据库失败时的补偿

文件系统和 PostgreSQL 无法共享普通 ACID 事务，所以使用补偿逻辑：

```text
文件写入成功
→ 数据库 INSERT 失败
→ 删除已经写入的文件
→ 向上抛出异常
```

这不是分布式事务，而是针对当前单机存储的显式补偿。

---

## 5. GET 列表接口与数据库分页

请求：

```http
GET /api/v1/documents?offset=0&limit=20
```

FastAPI 在进入路由前验证：

```text
offset >= 0
1 <= limit <= 100
```

旧实现先读取全部 JSON 再切片。数据库版现在执行：

```sql
SELECT ...
FROM documents
ORDER BY created_at DESC, id
OFFSET :offset
LIMIT :limit;
```

并单独统计：

```sql
SELECT count(*) FROM documents;
```

响应：

```json
{
  "items": [],
  "total": 0,
  "offset": 0,
  "limit": 20
}
```

数据库分页避免把整张表加载进 Python。数据量很大时，深 OFFSET 仍可能变慢，后续可以学习基于 `created_at + id` 的游标分页。

---

## 6. GET 详情接口

```http
GET /api/v1/documents/{document_id}
```

调用链：

```text
Router
→ service.get_document(id)
→ repository.get_by_id(id)
→ session.get(DocumentORM, UUID)
```

数据库不存在记录时，Repository 抛出：

```text
DocumentNotFoundError
```

Router 转换为：

```text
HTTP 404 Not Found
```

非法 UUID 也不会把 psycopg 的类型错误泄露给客户端，而是作为不存在处理。

---

## 7. DELETE 删除接口

```http
DELETE /api/v1/documents/{document_id}
```

成功返回：

```text
204 No Content
```

204 响应不能包含 JSON 响应体。

### 删除一致性策略

直接“先删文件再删数据库”存在风险：数据库失败后记录还在，但文件已经丢失。

当前实现：

```text
把文件原子改名为 .deleting 暂存文件
→ 删除数据库元数据并 commit
→ 数据库失败：把暂存文件改回原名
→ 数据库成功：永久删除暂存文件
```

如果数据库已经提交，但最后永久删除暂存文件失败，系统会记录错误日志并留下无引用的隐藏文件，而不会留下指向不存在文件的数据库记录。生产系统可以增加定时任务清理这些孤儿文件。

---

## 8. HTTP 状态码与异常映射

| 场景 | 状态码 |
| --- | ---: |
| 上传成功 | 201 |
| 查询成功 | 200 |
| 删除成功且无响应体 | 204 |
| FastAPI/Pydantic 参数校验失败 | 422 |
| 文件名、扩展名或大小不合法 | 400 |
| 主键或唯一路径冲突 | 409 |
| 文档不存在 | 404 |
| 未恢复的存储失败 | 500 |
| 当前预留 PATCH | 501 |

异常分层：

```text
PostgreSQL IntegrityError
→ Repository rollback
→ DocumentConflictError
→ Router 409
```

```text
数据库无对应行
→ DocumentNotFoundError
→ Router 404
```

Router 不把 SQL、数据库地址、内部路径和异常堆栈返回给客户端。

---

## 9. 响应模型为什么不会暴露路径

领域对象包含：

```text
original_path
stored_path
```

但 `DocumentResponse` 没有这两个字段。路由使用：

```python
DocumentResponse.model_validate(document)
```

最终响应只包含公开字段：

```text
id、name、file_type、file_size、status、created_at
```

响应过滤是 API 安全边界的一部分，不能直接返回 `document.__dict__`。

---

## 10. 留给你的 PATCH 接口

路由已经注册：

```http
PATCH /api/v1/documents/{document_id}
```

当前会返回：

```text
501 Not Implemented
```

请求模型 `DocumentUpdateRequest` 已完成，只允许：

```json
{
  "name": "新的文件名.txt",
  "status": "ready"
}
```

允许状态：

```text
uploaded、processing、ready、failed
```

空对象以及非法状态会在进入路由前返回 422。

Service 已提供：

```python
service.update_document(
    document_id,
    name=payload.name,
    document_status=payload.status,
)
```

Repository 的 `update()` 也已完成。因此你的任务只在：

```text
src/knowledge_assistant/api/routes/documents.py
```

找到 `update_document()` 的 TODO，然后完成：

1. 调用 `service.update_document()`。
2. 把 `DocumentNotFoundError` 转换为 404。
3. 把 `InvalidDocumentError` 转换为 400。
4. 把 `DocumentConflictError` 转换为 409。
5. 返回 `DocumentResponse.model_validate(document)`。
6. 将原先的 501 测试改为成功、404 和校验测试。

先自己尝试，不需要修改 Session、Repository 或数据库表。

---

## 11. Swagger 手工演示

启动：

```powershell
uvicorn knowledge_assistant.api.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/docs
```

建议演示顺序：

```text
POST 上传文件
→ 复制响应中的 id
→ GET 列表
→ GET 详情
→ PATCH（完成练习后）
→ DELETE
→ 再 GET，确认 404
```

---

## 12. PowerShell 调用示例

PowerShell 7 可以使用：

```powershell
$result = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/documents" `
  -Form @{ file = Get-Item "samples\example.txt" }
```

查看 ID：

```powershell
$result.id
```

列表：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/documents?offset=0&limit=20"
```

详情：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/documents/$($result.id)"
```

删除：

```powershell
Invoke-WebRequest `
  -Method Delete `
  -Uri "http://127.0.0.1:8000/api/v1/documents/$($result.id)"
```

Windows PowerShell 5.1 的 `Invoke-RestMethod` 没有完整 `-Form` 体验时，优先使用 Swagger，或者使用系统安装的 `curl.exe`：

```powershell
curl.exe -X POST `
  -F "file=@samples/example.txt" `
  http://127.0.0.1:8000/api/v1/documents
```

---

## 13. 测试分层

### 原有 API 测试

通过依赖覆盖使用 JSON Repository，快速验证路由、Pydantic 和响应过滤。

### PostgreSQL API 集成测试

`test_api_database.py` 使用：

```text
TestClient
→ FastAPI
→ DocumentService
→ SqlAlchemyDocumentRepository
→ knowledge_assistant_test
```

它通过 Alembic 准备测试库，覆盖：

- 中文文件名上传。
- PostgreSQL 元数据写入。
- 文件副本存在。
- 列表与详情。
- 204 删除。
- 删除后文件和元数据都不存在。
- 非法扩展名 400。
- 不存在文档 404。
- PATCH 当前预留 501。

### Service 故障测试

- 元数据新增失败时清理文件。
- 文件超过限制时清理部分文件。
- 元数据删除失败时恢复暂存文件。

---

## 14. 当前验证结果

```text
pytest：53 passed
Ruff：All checks passed
mypy：Success: no issues found in 24 source files
Alembic：20260813_02 (head)
```

PATCH 是有意保留的练习接口。完成并补测试后，阶段 6 才达到完整 CRUD 的最终完成状态。
