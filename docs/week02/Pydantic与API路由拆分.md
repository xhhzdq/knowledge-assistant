# Pydantic Schema 与 FastAPI 路由原理

> 对应阶段：第二周阶段 2  
> 涉及技术：Pydantic BaseModel、Field、请求/响应模型、response_model、路径参数、查询参数、APIRouter、Depends  
> 项目接口：`GET /api/v1/documents`、`GET /api/v1/documents/{document_id}`

---

## 1. 本阶段解决的问题

第一周只有 CLI：

```text
用户输入命令
  → argparse 解析参数
  → CLI 调用 DocumentService
  → Repository 访问 JSON
```

第二周增加 HTTP 入口：

```text
客户端发送 HTTP 请求
  → FastAPI 匹配路由
  → 解析并校验参数
  → Depends 注入 DocumentService
  → Router 调用 Service
  → Pydantic 校验和序列化响应
  → 返回 HTTP JSON
```

当前 API 仍复用第一周的 JSON Repository。阶段 2 的重点不是数据库，而是建立清晰的 HTTP 边界。

---

## 2. 一次请求的完整执行过程

以这个请求为例：

```http
GET /api/v1/documents?offset=1&limit=10
```

### 2.1 应用启动阶段

Uvicorn 导入：

```text
knowledge_assistant.api.main:app
```

Python 加载 `main.py`，创建 FastAPI 实例：

```python
app = FastAPI(...)
```

随后执行：

```python
app.include_router(documents_router)
```

文档 Router 中的装饰器已经在模块加载时执行：

```python
@router.get("", response_model=DocumentListResponse)
```

它把路径、HTTP 方法、处理函数、参数规则和响应模型注册到 Router。FastAPI 再把 Router 中的路由合并到主应用。

此时 FastAPI 建立了一张近似的路由表：

```text
GET /health                          → health_check
GET /api/v1/documents               → list_documents
GET /api/v1/documents/{document_id} → get_document
```

FastAPI 还会读取函数签名和 Pydantic 模型，生成 OpenAPI Schema，因此 Swagger 能自动显示接口、参数和响应结构。

### 2.2 请求到达阶段

请求到达后：

```text
GET /api/v1/documents?offset=1&limit=10
  ↓
FastAPI 根据 HTTP 方法和完整路径匹配 list_documents
  ↓
读取 offset="1"、limit="10"（HTTP 原始值是文本）
  ↓
转换为 int，并检查 offset >= 0、1 <= limit <= 100
  ↓
解析 Depends，调用 get_document_service()
  ↓
获得 DocumentService 实例
  ↓
调用 list_documents(service=..., offset=1, limit=10)
```

路由函数得到的 `offset` 和 `limit` 已经是经过校验的整数，不需要自己再调用 `int()`。

### 2.3 响应阶段

路由返回 `DocumentListResponse` 后：

```text
DocumentListResponse 对象
  ↓
FastAPI 按 response_model 再次验证响应结构
  ↓
Pydantic 将嵌套模型转换为可 JSON 序列化的数据
  ↓
JSON 编码
  ↓
HTTP 200 响应
```

客户端最终收到类似：

```json
{
  "items": [
    {
      "id": "document-2",
      "name": "second.pdf",
      "file_type": ".pdf",
      "file_size": 128,
      "status": "uploaded",
      "created_at": "2026-08-12T10:00:00+00:00"
    }
  ],
  "total": 3,
  "offset": 1,
  "limit": 10
}
```

---

## 3. Pydantic BaseModel

### 3.1 BaseModel 是什么

`BaseModel` 是 Pydantic 提供的模型基类：

```python
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: str
    name: str
    file_size: int
```

继承它后，Pydantic 会根据类型注解建立字段定义，并提供：

- 运行时数据校验。
- 必填字段检查。
- 合理范围内的类型转换。
- 嵌套模型处理。
- 字典和 JSON 序列化。
- JSON Schema 生成。
- 明确的校验错误信息。

### 3.2 BaseModel 与 dataclass 的区别

项目中已有：

```python
@dataclass
class Document:
    id: str
    file_size: int
```

两者职责不同：

| 对比项 | Document dataclass | Pydantic BaseModel |
| --- | --- | --- |
| 主要用途 | 程序内部领域数据 | API 输入/输出边界 |
| 来源 | Python 标准库 | 第三方 Pydantic |
| 运行时校验 | 默认没有 | 有 |
| JSON Schema | 默认没有 | 自动生成 |
| FastAPI OpenAPI | 不擅长直接描述 | 原生集成 |
| 错误详情 | 需要自行实现 | 自动产生结构化错误 |

领域模型不需要因为引入 FastAPI 就被删除。CLI、后台任务和测试仍可使用 `Document`，API 使用 Pydantic Schema 控制外部契约。

### 3.3 BaseModel 什么时候校验

直接创建模型时：

```python
DocumentResponse(
    id="document-1",
    name="guide.pdf",
    file_type=".pdf",
    file_size=-1,
    status="uploaded",
    created_at="2026-08-12T10:00:00+00:00",
)
```

由于 `file_size` 规定 `ge=0`，模型创建时会立即抛出 `ValidationError`。

在 FastAPI 中，Pydantic 校验可能发生在两个方向：

```text
请求数据 → 请求模型校验 → 路由函数
路由返回 → 响应模型校验 → 客户端
```

---

## 4. 字段类型和运行时校验

### 4.1 类型注解成为校验规则

Schema 中：

```python
id: str
file_size: int
items: list[DocumentResponse]
```

分别表示：

- `id` 应是字符串。
- `file_size` 应是整数。
- `items` 应是列表，且每个元素都符合 `DocumentResponse`。

这不只是给 mypy 看的。因为类继承了 `BaseModel`，Pydantic 会在运行时读取这些类型注解并执行校验。

### 4.2 静态类型检查与运行时校验

两者不要混淆：

```text
mypy
→ 开发阶段检查源代码中的类型使用
→ 不处理真实 HTTP 请求

Pydantic
→ 程序运行时检查实际收到的数据
→ 可以处理客户端输入和响应对象
```

例如客户端发送：

```text
limit=abc
```

mypy 无法提前知道客户端会传什么；FastAPI/Pydantic 会在请求运行时发现 `abc` 不能转换成整数，并返回 422。

### 4.3 类型转换不是无限制的

Pydantic 可以进行部分合理转换，例如 HTTP 查询参数原始上都是字符串：

```text
"10" → 10
```

但：

```text
"abc" → int
```

无法完成，因此产生校验错误。

---

## 5. Field 的作用

### 5.1 基本形式

```python
file_size: int = Field(
    ge=0,
    description="文件大小，单位为字节",
)
```

字段本身是 `int`，`Field` 增加了额外元数据和约束。

### 5.2 当前项目使用的约束

| 配置 | 含义 | 项目示例 |
| --- | --- | --- |
| `default` | 默认值 | 更新字段默认 `None` |
| `ge` | 大于或等于 | `file_size >= 0` |
| `le` | 小于或等于 | `limit <= 100` |
| `min_length` | 字符串最小长度 | 名称不能为空字符串 |
| `max_length` | 字符串最大长度 | 名称最多 255 个字符 |
| `description` | OpenAPI 字段说明 | Swagger 中显示中文说明 |

### 5.3 可选字段不等于任意内容

```python
name: str | None = Field(
    default=None,
    min_length=1,
    max_length=255,
)
```

含义是：

```text
允许不提供/为 None
如果提供字符串，则长度必须为 1～255
```

它不是说所有值都合法。

### 5.4 Field 对 Swagger 的影响

`description`、范围和长度约束会进入 JSON Schema/OpenAPI。Swagger UI 因此能够展示字段说明，客户端代码生成工具也能读取这些约束。

---

## 6. 请求模型与响应模型

### 6.1 请求模型

请求模型描述“客户端允许传入什么”。例如未来 PATCH 接口：

```python
class DocumentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, min_length=1, max_length=32)
```

它只允许客户端修改 `name` 和 `status`。

没有包含：

```text
id
stored_path
file_size
created_at
```

所以客户端不能通过这个请求模型直接修改系统管理字段。

### 6.2 响应模型

响应模型描述“服务器承诺向客户端返回什么”：

```python
class DocumentResponse(BaseModel):
    id: str
    name: str
    file_type: str
    file_size: int
    status: str
    created_at: str
```

没有包含内部路径，因此这些路径不会成为公开 API 契约。

### 6.3 为什么不能只用一个模型

创建、修改和返回数据的权限范围通常不同：

```text
创建请求：客户端提供文件和部分描述信息
更新请求：客户端只修改允许字段
响应：服务器返回 ID、状态、创建时间等系统字段
```

如果全部使用一个模型，容易让客户端误以为可以设置 `id`、`created_at` 或 `stored_path`。

模型分开不是为了制造重复代码，而是为了表达不同的数据契约和权限边界。

---

## 7. response_model 的过滤和序列化

### 7.1 当前用法

```python
@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
)
```

`response_model` 告诉 FastAPI：无论路由内部返回什么兼容对象，最终公开响应都必须符合 `DocumentResponse`。

### 7.2 过滤原理

内部 `Document` 有八个字段：

```text
id
name
original_path
stored_path
file_type
file_size
status
created_at
```

`DocumentResponse` 只有六个字段。响应处理时，FastAPI/Pydantic 只保留 Schema 声明的字段：

```text
Document
  ├── id            → 保留
  ├── name          → 保留
  ├── original_path → 过滤
  ├── stored_path   → 过滤
  ├── file_type     → 保留
  ├── file_size     → 保留
  ├── status        → 保留
  └── created_at    → 保留
```

这是一层防止意外暴露内部数据的保护。

### 7.3 序列化原理

Python 对象不能直接成为网络中的 JSON 字节。响应过程需要：

```text
Python/Pydantic 对象
  → Python dict/list/str/int 等基础结构
  → JSON 文本/字节
  → HTTP 响应体
```

Pydantic 负责把嵌套模型及支持的复杂类型转换成 JSON 兼容值，FastAPI 再构造 HTTP 响应。

### 7.4 from_attributes=True

当前代码：

```python
model_config = ConfigDict(from_attributes=True)
```

配合：

```python
DocumentResponse.model_validate(document)
```

默认情况下，Pydantic 更自然地从字典读取：

```python
data["id"]
```

`from_attributes=True` 允许它从对象属性读取：

```python
document.id
```

因此可以直接把 dataclass 领域对象转换为响应模型。

### 7.5 response_model 不是数据库安全的全部保证

它只过滤最终 HTTP 响应，不代表内部日志、异常消息和其他接口一定安全。仍然需要人工审查错误信息和日志内容。

---

## 8. 路径参数和查询参数

### 8.1 路径参数

路由：

```python
@router.get("/{document_id}")
```

请求：

```http
GET /api/v1/documents/document-123
```

其中：

```text
document-123 → document_id
```

FastAPI 通过路由模板中的 `{document_id}` 与函数参数同名完成绑定：

```python
document_id: Annotated[
    str,
    Path(min_length=1, description="文档唯一 ID"),
]
```

路径参数用于标识具体资源，通常是必填的。

### 8.2 查询参数

请求：

```http
GET /api/v1/documents?offset=20&limit=10
```

`?` 后面的键值对是查询参数：

```python
offset: Annotated[int, Query(ge=0)] = 0
limit: Annotated[int, Query(ge=1, le=100)] = 20
```

它们适合控制列表的过滤、排序和分页，不用于确定路由本身。

### 8.3 FastAPI 如何判断参数来源

FastAPI 结合函数签名和声明判断：

```text
路径模板中存在 + Path(...) → 路径参数
Query(...)                  → 查询参数
Pydantic BaseModel          → 通常来自 JSON 请求体
Depends(...)                → 依赖系统提供
```

### 8.4 422 从哪里来

例如：

```http
GET /api/v1/documents?limit=0
```

在调用 `list_documents()` 前，FastAPI 已检查到 `limit` 违反 `ge=1`，因此直接返回 422。路由函数不会执行，Service 也不会被调用。

这可以防止非法数据进入业务层。

### 8.5 路径参数与查询参数的选择

推荐语义：

```text
/documents/{id}     → 定位一个资源
/documents?limit=10 → 调整列表查询方式
```

不建议写成：

```text
/documents?id=123
```

来替代清晰的单资源路径，除非接口本身确实是搜索语义。

---

## 9. APIRouter 与路由前缀

### 9.1 为什么需要 APIRouter

如果所有接口都写在 `main.py`：

```text
main.py
├── health
├── documents
├── users
├── tasks
├── agents
└── ...
```

文件会越来越大，模块职责混乱。

`APIRouter` 可以按业务资源拆分：

```text
api/routes/
├── documents.py
├── users.py
└── tasks.py
```

### 9.2 路由前缀

当前声明：

```python
router = APIRouter(
    prefix="/api/v1/documents",
    tags=["documents"],
)
```

接口自身只写相对部分：

```python
@router.get("")
@router.get("/{document_id}")
```

最终路径由前缀和相对路径拼接：

```text
/api/v1/documents + ""
= /api/v1/documents

/api/v1/documents + /{document_id}
= /api/v1/documents/{document_id}
```

### 9.3 tags 的作用

```python
tags=["documents"]
```

主要影响 OpenAPI/Swagger 分组，便于在文档页面按资源查看接口，不会改变 URL。

### 9.4 include_router

Router 自己不是独立运行的应用。必须在主应用中注册：

```python
app.include_router(documents_router)
```

如果忘记注册：

- 代码文件存在。
- 装饰器也执行了。
- 但主应用路由表没有这些路径。
- 请求会得到 404。
- Swagger 也看不到接口。

---

## 10. Depends 依赖注入

### 10.1 当前声明

```python
DocumentServiceDependency = Annotated[
    DocumentService,
    Depends(get_document_service),
]
```

路由函数使用：

```python
def list_documents(
    service: DocumentServiceDependency,
    ...,
):
```

含义不是“客户端必须传入 service”，而是：

> 执行路由前，FastAPI 应调用 `get_document_service()`，把返回值作为 `service` 参数。

### 10.2 请求期间的执行过程

```text
请求匹配 list_documents
  ↓
FastAPI 检查函数参数
  ↓
发现 service 使用 Depends(get_document_service)
  ↓
调用 get_document_service()
  ↓
创建 Settings
  ↓
创建 JsonDocumentRepository
  ↓
创建 DocumentService
  ↓
把对象传给 service 参数
  ↓
执行 list_documents(...)
```

### 10.3 为什么不在路由中直接创建 Service

不推荐：

```python
def list_documents():
    settings = Settings.default()
    repository = JsonDocumentRepository(...)
    service = DocumentService(...)
```

因为每个接口都会重复组装代码，而且测试很难替换真实数据源。

使用 Depends 后，Router 只关心：

```text
我需要一个 DocumentService
```

而不关心：

```text
它现在来自 JSON、以后来自 PostgreSQL，还是测试临时对象
```

### 10.4 测试中的 dependency_overrides

测试代码：

```python
app.dependency_overrides[get_document_service] = lambda: service
```

请求测试时，FastAPI 不再调用正式依赖，而是调用覆盖函数：

```text
正式运行：get_document_service → 项目 data 目录
测试运行：lambda → pytest 临时目录 Service
```

因此测试不会污染真实数据，也不需要修改业务路由代码。

测试结束后必须清理：

```python
app.dependency_overrides.clear()
```

否则覆盖可能影响后续测试。

### 10.5 Depends 不只是创建对象

以后可以用于：

- 获取和关闭数据库 Session。
- 读取当前登录用户。
- 权限验证。
- 公共查询参数。
- 配置和外部客户端。

依赖还可以依赖其他依赖，FastAPI 会建立依赖关系图，按顺序解析。

### 10.6 当前实现的生命周期局限

当前 `get_document_service()` 每次调用都会创建新的 Service 和 Repository 对象。它们只包含轻量文件路径，没有长期连接，因此问题不大。

后续 SQLAlchemy Session 需要在请求结束时可靠关闭，届时依赖通常会使用 `yield`：

```python
def get_session():
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
```

FastAPI 会在请求处理完成后执行 `finally`，释放数据库资源。

---

## 11. 文档详情接口的异常转换

当前实现：

```python
try:
    document = service.get_document(document_id)
except DocumentNotFoundError as exc:
    raise HTTPException(
        status_code=404,
        detail=str(exc),
    ) from exc
```

分层含义：

```text
Repository/Service
→ 只知道“文档不存在”
→ 抛出 DocumentNotFoundError

API Router
→ 知道 HTTP 语义
→ 转换成 HTTP 404
```

Service 不应直接抛 `HTTPException`，否则 CLI 使用同一个 Service 时也被迫依赖 HTTP 概念。

本次练习中发现：

1. `get_document` 是实例方法，应调用 `service.get_document(document_id)`。
2. 找不到文档时会抛异常，不会返回 `None`，因此不能依靠 `if not document`。

---

## 12. 当前项目的完整结构关系

```text
main.py
  │ include_router
  ▼
documents Router
  │ Depends
  ▼
get_document_service
  │ 创建
  ▼
DocumentService
  │ 调用
  ▼
JsonDocumentRepository
  │ 读取
  ▼
documents.json

返回方向：

documents.json
  → DocumentData
  → Document
  → DocumentResponse / DocumentListResponse
  → FastAPI JSON 响应
```

当前 JSON Repository 是临时实现。进入 PostgreSQL 阶段后，会替换依赖函数中的 Repository 组装方式，Router 的核心调用方式应尽量保持不变。

---

## 13. 常见误区

### 误区 1：BaseModel 只是类型注解

不是。继承 BaseModel 后，类型注解会参与运行时校验和 Schema 生成。

### 误区 2：有了 Pydantic 就不需要 mypy

不是。Pydantic 检查运行时数据，mypy 检查源码中的静态类型，它们处理不同问题。

### 误区 3：response_model 只是 Swagger 说明

不是。它也会在运行时校验、过滤和序列化响应。

### 误区 4：路径参数和查询参数都只是字符串

HTTP 原始数据确实来自文本，但 FastAPI 会根据声明转换并校验，路由函数收到的是目标 Python 类型。

### 误区 5：APIRouter 创建后会自动生效

不会。必须通过 `app.include_router()` 注册到 FastAPI 主应用。

### 误区 6：Depends 的参数由客户端传入

不是。依赖参数由 FastAPI 调用依赖函数后注入。

### 误区 7：Router 可以直接读取 JSON 或数据库

技术上可以，但会破坏分层并增加测试难度。当前约定是 Router 调用 Service，Service 再调用 Repository。

---

## 14. 可亲自运行的验证实验

### 实验 1：查看 OpenAPI 自动生成结果

启动：

```powershell
uvicorn knowledge_assistant.api.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/docs
```

观察：

- documents 标签。
- offset 和 limit 的默认值与范围。
- DocumentResponse 字段。
- 404 响应描述。

### 实验 2：验证查询参数转换

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/documents?offset=0&limit=10"
```

虽然 URL 中的 `10` 是文本，路由函数收到的是整数。

### 实验 3：验证 422

```powershell
Invoke-WebRequest "http://127.0.0.1:8000/api/v1/documents?limit=0" -SkipHttpErrorCheck
```

预期状态码：

```text
422
```

因为 `limit` 必须大于或等于 1，且路由函数不会执行。

### 实验 4：验证 404

```powershell
Invoke-WebRequest "http://127.0.0.1:8000/api/v1/documents/not-exist" -SkipHttpErrorCheck
```

预期状态码：

```text
404
```

### 实验 5：验证 response_model 过滤

先通过 CLI 添加一份样例文档：

```powershell
knowledge-assistant add .\samples\example.txt
```

再请求列表：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/documents"
```

对比 `data/documents.json`：JSON 存储中存在内部路径，API 响应中没有。

### 实验 6：只运行 API 测试

```powershell
pytest tests\test_api.py --basetemp=.pytest-tmp-api -v
```

重点观察测试名称与每个概念的映射：分页、字段过滤、422、详情和 404。

---

## 15. 自测问题

能够独立回答以下问题，说明阶段 2 原理基本掌握：

1. Pydantic BaseModel 与 Python dataclass 的职责有什么区别？
2. `file_size: int` 在 Pydantic 模型中何时进行运行时校验？
3. `Field(ge=0)` 和 `Field(description="...")` 分别影响什么？
4. 为什么更新请求和详情响应不应共用一个模型？
5. `response_model` 为什么能够隐藏 `stored_path`？
6. `offset=abc` 为什么在进入路由函数前就返回 422？
7. `{document_id}` 如何与函数参数绑定？
8. Router 的 `prefix` 如何组成最终 URL？
9. 忘记 `include_router` 会出现什么现象？
10. 客户端没有传 `service`，路由为什么能获得它？
11. `dependency_overrides` 为什么能防止测试污染正式数据？
12. 为什么 Service 抛 `DocumentNotFoundError`，Router 再转换为 HTTP 404？

---

## 16. 阶段结论

阶段 2 建立了一个清晰的 API 边界：

```text
FastAPI
→ 负责路由匹配、参数来源判断和 HTTP 响应

Pydantic
→ 负责运行时数据校验、响应过滤、序列化和 Schema

APIRouter
→ 负责按业务资源组织接口

Depends
→ 负责组装并注入 Service，使路由与具体存储实现解耦
```

当前接口已经能够使用 JSON Repository 独立运行。下一阶段接入 PostgreSQL 时，主要变化应该发生在依赖组装和 Repository 层，而不是重新编写整套路由规则。
