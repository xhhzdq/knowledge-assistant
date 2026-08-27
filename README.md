# Knowledge Assistant

企业文档智能问答系统学习项目。目前已经完成 Python 工程骨架、命令行文档管理工具，以及基于 FastAPI、PostgreSQL、SQLAlchemy 和 Alembic 的文档 CRUD API。后续将逐步接入 Redis、容器化、文档解析、向量检索、Agent 与 MCP。

## 环境要求

- Python 3.11 或更高版本
- Git
- PostgreSQL 17（本地开发阶段）

## 初始化开发环境

在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 验证环境

```powershell
knowledge-assistant --help
pytest --basetemp=.pytest-tmp
ruff check .
mypy
```

涉及数据库的测试只允许连接名称以 `_test` 结尾的独立测试数据库。请根据 `.env.example` 创建本地 `.env`，不要提交真实密码。

## 命令行使用

```powershell
knowledge-assistant add .\samples\example.txt
knowledge-assistant list
knowledge-assistant show <document-id>
knowledge-assistant delete <document-id>
```

`add` 会将文件副本保存到 `data/uploads`，并将元数据保存到首次运行时自动创建的 `data/documents.json`。

命令行是第一周保留的 JSON Repository 示例；第二周的 HTTP API 已改用 PostgreSQL。两条入口目前可以同时使用，但数据源彼此独立。

## 数据库迁移

```powershell
alembic current
alembic upgrade head
alembic history
```

首次启动 API 前应执行 `alembic upgrade head`。表结构由 Alembic 管理，不在应用启动时调用 `create_all()` 自动建表。

## 启动 API

```powershell
uvicorn knowledge_assistant.api.main:app --reload
```

启动后可以访问：

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

文档接口统一使用 `/api/v1/documents` 前缀：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v1/documents` | 上传文档并保存文件与元数据 |
| `GET` | `/api/v1/documents` | 分页查询文档 |
| `GET` | `/api/v1/documents/{id}` | 查询文档详情 |
| `PATCH` | `/api/v1/documents/{id}` | 修改文档名称或处理状态 |
| `DELETE` | `/api/v1/documents/{id}` | 删除文件及数据库元数据 |

## 当前目录结构

```text
knowledge-assistant/
├── src/knowledge_assistant/  # 应用源码
│   ├── api/                  # FastAPI 入口、依赖和路由
│   ├── db/                   # SQLAlchemy ORM、Engine 和 Session
│   ├── repositories/         # JSON 与 SQLAlchemy Repository
│   ├── schemas/              # Pydantic 请求/响应模型
│   └── services/             # 文档业务逻辑
├── migrations/               # Alembic 数据库迁移
├── tests/                    # 自动化测试
├── data/uploads/             # 本地文档副本（不提交到 Git）
├── docs/week01/              # 第一周学习文档
├── docs/week02/              # 第二周 Web 与关系数据库文档
├── pyproject.toml            # 项目与工具配置
└── README.md
```

## 当前状态

已完成命令行文档管理、FastAPI 文档 CRUD、PostgreSQL 持久化、SQLAlchemy Repository、Alembic 两次迁移及相应自动化测试。当前只保存文件及元数据，不解析 PDF 正文，也不进行 OCR、Embedding 或向量检索。
