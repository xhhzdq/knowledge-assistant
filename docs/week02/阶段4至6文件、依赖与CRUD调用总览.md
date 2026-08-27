# 阶段 4～6：文件、依赖与 CRUD 调用总览

> 阅读建议：先用本文建立文件和调用关系，再阅读《PostgreSQL 原理、常用方法与表结构设计》《SQLAlchemy 原理、ORM、Session 与事务》《Alembic 原理、常用方法与数据库版本管理》。三份专题文档既讲项目落地，也包含通用原理、常用 API/命令、排障与进阶实践。

## 1. 先记住整体结论

阶段 4～6 分别解决三个问题：

```text
阶段 4：Python 程序怎样读写数据库中的数据
阶段 5：数据库中的表怎样创建和升级
阶段 6：HTTP 请求怎样经过业务层完成文档 CRUD
```

对应两条相互关联、但运行时彼此独立的链：

```text
数据 CRUD 链：
Document → Repository → Session → Engine → PostgreSQL

表结构迁移链：
alembic 命令 → env.py → 迁移文件 → PostgreSQL

HTTP API 链：
FastAPI Router → DocumentService → Repository → PostgreSQL / 文件系统
```

二者都参考 `DocumentORM` 描述的最终表结构，但作用不同：

- SQLAlchemy Repository 操作表中的数据。
- Alembic 创建、修改和回退表结构。
- FastAPI 接收 HTTP 请求并把业务操作交给 Service。

---

## 2. 新增和修改的文件总览

```text
knowledge-assistant/
├── .env                                      # 真实数据库连接地址，不提交 Git
├── .env.example                              # 数据库连接示例，可提交 Git
├── alembic.ini                               # Alembic 总入口配置
│
├── migrations/
│   ├── env.py                                # Alembic 运行环境
│   ├── script.py.mako                        # 新迁移文件的模板
│   ├── README                                # Alembic 常用命令
│   └── versions/
│       ├── 20260813_01_create_documents_table.py
│       └── 20260813_02_add_updated_at_to_documents.py
│
├── src/knowledge_assistant/
│   ├── core/
│   │   └── config.py                         # 新增 DatabaseSettings
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                           # Declarative Base
│   │   ├── models.py                         # DocumentORM
│   │   └── session.py                        # Engine、Session Factory
│   ├── repositories/
│   │   ├── base.py                           # Repository 抽象协议
│   │   └── sqlalchemy_repository.py          # PostgreSQL CRUD 实现
│   ├── api/
│   │   ├── main.py                           # FastAPI 应用入口
│   │   ├── dependencies.py                   # Engine、Session、Service 依赖组装
│   │   └── routes/
│   │       └── documents.py                  # 文档 HTTP CRUD 路由
│   ├── schemas/
│   │   └── documents.py                      # 请求和响应 Schema
│   └── services/
│       └── document_service.py               # 文件操作和文档业务规则
│
└── tests/
    ├── test_api.py                           # 快速 API 路由测试
    ├── test_api_database.py                  # HTTP 到 PostgreSQL 集成测试
    ├── test_sqlalchemy_repository.py         # 数据 CRUD 集成测试
    └── test_migrations.py                    # 表结构迁移测试
```

---

## 3. 配置层文件

### 3.1 `.env`

作用：保存本机真实数据库连接地址。

```dotenv
DATABASE_URL=postgresql+psycopg://knowledge_app:真实密码@127.0.0.1:5432/knowledge_assistant_dev
TEST_DATABASE_URL=postgresql+psycopg://knowledge_app:真实密码@127.0.0.1:5432/knowledge_assistant_test
```

它被 `.gitignore` 忽略，不能提交 Git。

### 3.2 `.env.example`

作用：告诉其他人项目需要哪些环境变量，但不包含真实密码。

```dotenv
DATABASE_URL=postgresql+psycopg://knowledge_app:CHANGE_ME@127.0.0.1:5432/knowledge_assistant_dev
TEST_DATABASE_URL=postgresql+psycopg://knowledge_app:CHANGE_ME@127.0.0.1:5432/knowledge_assistant_test
```

### 3.3 `core/config.py`

原来已有的 `Settings` 继续负责文件和日志目录。

阶段 4 新增 `DatabaseSettings`，负责把 `.env` 中的字符串读取成 Python 配置对象：

```text
.env
  ↓ pydantic-settings
DatabaseSettings
  ├── database_url
  └── test_database_url
```

依赖它的文件：

- `db/session.py`：读取开发库连接地址。
- `migrations/env.py`：确定迁移操作哪个数据库。
- 两个数据库测试文件：读取测试库地址。

---

## 4. 数据库模型层文件

### 4.1 `db/base.py`

作用：定义所有 ORM 模型共同继承的基类。

```python
class Base(DeclarativeBase):
    pass
```

可以把 `Base.metadata` 理解为“SQLAlchemy 已登记的全部表结构目录”。

当前关系：

```text
Base
└── DocumentORM
```

以后增加用户表或文本切片表，也会继承同一个 Base。

### 4.2 `db/models.py`

作用：定义 `DocumentORM`，把 Python 属性映射到 PostgreSQL 的 `documents` 表。

```text
DocumentORM.id          ↔ documents.id
DocumentORM.name        ↔ documents.name
DocumentORM.file_size   ↔ documents.file_size
DocumentORM.updated_at  ↔ documents.updated_at
```

它还定义：

- 字段类型。
- 是否允许为空。
- 默认值。
- 主键和唯一约束。
- 检查约束。
- 索引。

`DocumentORM` 是数据库模型，不是 API 请求模型，也不是业务领域模型。

三个容易混淆的模型：

| 模型 | 文件 | 作用 |
| --- | --- | --- |
| `Document` | `models.py` | Service 使用的领域对象 |
| `DocumentResponse` | `schemas/documents.py` | FastAPI 对外返回的数据 |
| `DocumentORM` | `db/models.py` | PostgreSQL 表的一行 |

### 4.3 为什么导入 `DocumentORM` 很重要

当 Python 执行 `db/models.py` 中的类定义后，`documents` 表才会登记到：

```text
Base.metadata
```

因此 Alembic 的 `env.py` 中有：

```python
from knowledge_assistant.db import models
```

它看起来没有直接调用 `models`，实际作用是执行模块并完成表结构注册。

---

## 5. 数据库连接层文件

### `db/session.py`

作用：创建 Engine 和 Session Factory。

其中三个函数分别是：

```text
create_db_engine(database_url)
→ 根据指定 URL 创建 Engine

create_session_factory(engine)
→ 根据 Engine 创建 Session 工厂

create_default_engine()
→ 从 DatabaseSettings 读取开发库 URL，再创建 Engine
```

关系如下：

```text
DatabaseSettings.database_url
            ↓
     create_db_engine()
            ↓
          Engine
            ↓
 create_session_factory()
            ↓
       Session Factory
            ↓
          Session
```

- Engine 管理数据库连接池。
- Session Factory 用来创建 Session。
- Session 管理一次 ORM 工作和事务。

不要把一个 Session 永久全局复用。后续 FastAPI 通常每个请求创建一个 Session，请求结束后关闭。

---

## 6. Repository 层文件

### 6.1 `repositories/base.py`

作用：定义 `DocumentRepository` 协议，也就是 Service 对存储层提出的要求。

```text
list_all()
get_by_id()
add()
delete()
```

Service 只依赖这个能力清单，不关心底层使用 JSON 还是 PostgreSQL。

```text
                     ┌→ JsonDocumentRepository
DocumentRepository ─┤
                     └→ SqlAlchemyDocumentRepository
```

### 6.2 `services/document_service.py` 的变化

之前构造函数明确要求：

```text
JsonDocumentRepository
```

现在改为要求：

```text
DocumentRepository
```

因此同一个 Service 可以搭配不同实现：

```python
DocumentService(json_repository, uploads_dir)
```

或者：

```python
DocumentService(sqlalchemy_repository, uploads_dir)
```

这就是依赖抽象，而不是依赖具体存储技术。

### 6.3 `repositories/sqlalchemy_repository.py`

作用：使用 Session 操作 `DocumentORM`，完成 PostgreSQL CRUD。

它依赖：

```text
Session
DocumentORM
Document
DocumentNotFoundError / StorageError
```

它负责两种转换：

```text
Document → DocumentORM → 数据库
数据库 → DocumentORM → Document
```

这样 Service 最终收到的仍是 `Document`，不会被迫理解 SQLAlchemy。

它实现的方法：

```text
add()        → INSERT 并 commit
list_all()   → SELECT 全部
get_by_id()  → 按主键 SELECT
update()     → UPDATE 并 commit
delete()     → DELETE 并 commit
```

写入失败时：

```text
数据库异常
  ↓
rollback
  ↓
转换为 StorageError
```

---

## 7. Alembic 文件

### 7.1 `alembic.ini`

作用：Alembic 命令的入口配置。

它告诉 Alembic：

- 迁移目录在 `migrations`。
- 项目源码在 `src`。
- 日志怎样输出。

它不保存真实数据库密码。真正的连接 URL 由 `env.py` 从 `.env` 读取。

### 7.2 `migrations/env.py`

作用：每次 Alembic 命令执行时，准备迁移环境。

它依赖：

```text
DatabaseSettings → 确定连接哪个数据库
db.models        → 注册 DocumentORM
Base.metadata    → 获得 ORM 最终结构
```

它不负责定义某次具体修改；具体修改在 `versions` 中。

### 7.3 `migrations/script.py.mako`

作用：以后创建新迁移文件时使用的代码模板。

例如运行：

```powershell
alembic revision --autogenerate -m "add description"
```

Alembic 会根据这个模板创建一个新的 Python 文件。

它不会在普通 `upgrade` 中改变数据库。

### 7.4 第一条迁移文件

文件：

```text
20260813_01_create_documents_table.py
```

作用：

```text
upgrade()   → 创建 documents 表、约束和索引
downgrade() → 删除索引和 documents 表
```

它的父版本是：

```python
down_revision = None
```

说明它是迁移链的第一条。

### 7.5 第二条迁移文件

文件：

```text
20260813_02_add_updated_at_to_documents.py
```

作用：

```text
upgrade()   → 添加 updated_at
downgrade() → 删除 updated_at
```

它依赖第一条迁移：

```python
down_revision = "20260813_01"
```

迁移顺序由 `revision` 和 `down_revision` 决定，不是简单按照文件名排序。

### 7.6 `migrations/README`

作用：记录 Alembic 常用命令，供开发人员查看，不参与程序执行。

---

## 8. 两个测试文件

### 8.1 `test_sqlalchemy_repository.py`

它测试的是“数据能不能正确增删改查”：

```text
测试代码
  ↓
SqlAlchemyDocumentRepository
  ↓
Session
  ↓
knowledge_assistant_test
```

覆盖新增、列表、详情、更新、删除、异常和回滚。

它关注的是表里面的数据，不负责证明 Alembic 迁移链正确。

### 8.2 `test_migrations.py`

它测试的是“表结构能不能正确升级和回退”：

```text
测试代码
  ↓
Alembic command
  ↓
迁移 01 / 迁移 02
  ↓
knowledge_assistant_test
```

覆盖：

- 第一条迁移创建表。
- 第二条迁移添加字段。
- 回退会删除字段。
- 回退后可以重新升级。
- 测试结束清空测试库。

两个测试文件不能互相替代：

```text
Repository 测试 → 验证数据 CRUD
Migration 测试  → 验证表结构演进
```

---

## 9. 运行 Repository 时的调用链

当前 API 已接入 PostgreSQL。一次详情查询的完整路径：

```text
HTTP GET /api/v1/documents/{id}
                ↓
FastAPI Router
                ↓
DocumentService.get_document()
                ↓
SqlAlchemyDocumentRepository.get_by_id()
                ↓
Session.get(DocumentORM, id)
                ↓
Engine 从连接池取得连接
                ↓
psycopg 向 PostgreSQL 发送 SELECT
                ↓
PostgreSQL 返回一行
                ↓
DocumentORM
                ↓ Repository 转换
Document
                ↓ API Schema 序列化
DocumentResponse JSON
```

当前实际状态是：

```text
CLI → DocumentService → JsonDocumentRepository
API → DocumentService → SqlAlchemyDocumentRepository → PostgreSQL
```

因此 CLI 继续演示第一周 JSON 存储，API 使用第二周 PostgreSQL 存储。两者目前不是同一份元数据。

---

## 10. 执行数据库迁移时的调用链

执行：

```powershell
alembic upgrade head
```

调用过程：

```text
alembic 命令
    ↓
读取 alembic.ini
    ↓
运行 migrations/env.py
    ├── DatabaseSettings 读取 DATABASE_URL
    ├── 导入 DocumentORM
    └── 取得 Base.metadata
    ↓
连接 PostgreSQL
    ↓
读取 alembic_version 当前版本
    ↓
根据 revision / down_revision 计算待执行迁移
    ↓
依次调用迁移文件的 upgrade()
    ↓
修改表结构
    ↓
更新 alembic_version
```

注意，这条链不会经过：

```text
FastAPI Router
DocumentService
SqlAlchemyDocumentRepository
```

迁移负责结构，Repository 负责数据，两者不会互相调用。

---

## 11. 核心依赖关系图

```mermaid
flowchart TD
    ENV[".env"] --> DS["DatabaseSettings"]

    DS --> SESSION["db/session.py"]
    SESSION --> ENGINE["Engine / Session Factory"]

    BASE["db/base.py · Base"] --> ORM["db/models.py · DocumentORM"]
    ENGINE --> REPO["SqlAlchemyDocumentRepository"]
    ORM --> REPO
    DOMAIN["Document 领域对象"] <--> REPO
    REPO -.符合.-> PROTOCOL["DocumentRepository 协议"]
    SERVICE["DocumentService"] --> PROTOCOL
    REPO --> PG[("PostgreSQL 数据")]

    CLIENT["HTTP Client / Swagger"] --> ROUTER["FastAPI Documents Router"]
    ROUTER --> SCHEMA["Pydantic Schema"]
    ROUTER --> SERVICE
    SERVICE --> FILES[("data/uploads")]

    INI["alembic.ini"] --> AENV["migrations/env.py"]
    DS --> AENV
    ORM --> BASEMETA["Base.metadata"]
    BASEMETA --> AENV
    AENV --> REV1["迁移 01"]
    REV1 --> REV2["迁移 02"]
    REV2 --> PGSCHEMA[("PostgreSQL 表结构")]
```

阅读时可以把左半边理解为“应用运行”，右半边理解为“数据库升级”。

---

## 12. 最容易混淆的五点

### 12.1 ORM 模型不等于真实表

修改 `DocumentORM` 只改变 Python 代码，不会自动改变数据库。

真正修改数据库的是：

```powershell
alembic upgrade head
```

### 12.2 Repository 不创建表

Repository 假设表已经存在，只负责查询和修改数据。

表不存在时执行 Repository 会收到数据库错误。

### 12.3 Alembic 不负责业务 CRUD

Alembic 创建表或增加字段，但不会处理上传文档、查询文档等业务请求。

### 12.4 Base.metadata 不是数据库

`Base.metadata` 是 Python 内存中的结构说明。Alembic 可以用它与真实数据库进行比较。

### 12.5 CLI 和 API 为什么看到的数据不同

当前两条组装链不同：

```text
CLI → JsonDocumentRepository → data/documents.json
API → SqlAlchemyDocumentRepository → PostgreSQL
```

---

## 13. 建议的理解顺序

第一次阅读时，只要依次理解下面九个文件：

```text
1. core/config.py
   → 数据库地址从哪里来

2. db/base.py
   → ORM 模型共同登记在哪里

3. db/models.py
   → documents 表在 Python 中怎么描述

4. db/session.py
   → Python 怎么连接数据库并创建 Session

5. repositories/sqlalchemy_repository.py
   → Session 怎么完成数据 CRUD

6. migrations/env.py + versions/
   → 表结构怎么真正创建和升级

7. api/dependencies.py
   → 每个 HTTP 请求怎样获得 Session 和数据库版 Service

8. api/routes/documents.py
   → HTTP 方法怎样转换成 Service 调用

9. schemas/documents.py
   → 请求校验和响应字段怎样控制
```

先不需要记住每一行代码。能够讲清楚下面这句话，就已经掌握了整体结构：

> `.env` 提供数据库地址，Engine 和 Session 管理连接与事务，DocumentORM 描述数据库表，Repository 使用 Session 操作 DocumentORM 并返回 Document；Alembic 单独管理表结构；FastAPI Router 校验 HTTP 输入并调用 Service，Service 协调文件系统和 Repository。

---

## 14. 当前完成状态

已经完成：

```text
PostgreSQL 用户和数据库
→ documents 表结构设计
→ SQLAlchemy ORM
→ Session 与 Repository CRUD
→ Alembic 两次迁移
→ 开发库升级到 head
→ FastAPI 接入数据库 Session
→ 上传、列表、详情、删除 API
```

当前开发库：

```text
alembic_version
documents
```

阶段 6 当前还保留一个学习任务：

```text
PATCH /api/v1/documents/{document_id}
→ 路由已注册
→ Service.update_document() 已实现
→ Repository.update() 已实现
→ 路由异常转换和响应留给学习者完成
```

CLI 暂时仍使用 JSON Repository，可以继续正常使用，不受数据库版 API 的影响。

---

## 15. 阶段 6 新增文件的职责

### 15.1 `api/dependencies.py`

负责把数据库基础设施组装成 Router 可以使用的 `DocumentService`：

```text
DatabaseSettings
→ Engine
→ Session Factory
→ 当前请求 Session
→ SqlAlchemyDocumentRepository
→ DocumentService
```

生命周期：

```text
Engine               → 一个 API 进程复用一个
Session              → 每个 HTTP 请求一个
Repository / Service → 每个请求根据当前 Session 组装
```

### 15.2 `api/routes/documents.py`

负责 HTTP 边界：

- 定义方法和路径。
- 接收文件、路径参数、查询参数和请求体。
- 调用 Service。
- 将领域异常转换成 HTTP 状态码。
- 使用 Pydantic Schema 生成响应。

Router 不直接操作 Session，不直接执行 SQL，也不自己复制文件。

### 15.3 `schemas/documents.py`

负责 HTTP 数据结构：

```text
DocumentResponse      → 单个文档公开字段
DocumentListResponse  → 分页响应
DocumentUpdateRequest → PATCH 允许修改的字段
```

`DocumentResponse` 不包含 `original_path` 和 `stored_path`，因此内部服务器路径不会出现在 HTTP JSON 中。

### 15.4 `test_api_database.py`

测试完整链路：

```text
TestClient
→ FastAPI
→ DocumentService
→ SqlAlchemyDocumentRepository
→ knowledge_assistant_test
```

它还检查文件副本是否创建和删除，而不只是检查响应 JSON。

---

## 16. API 请求共有的依赖调用过程

不论 POST、GET、PATCH 还是 DELETE，在进入路由前都会先解析依赖：

```text
HTTP 请求到达 FastAPI
        ↓
匹配 APIRouter 中的方法和路径
        ↓
解析 Depends(get_document_service)
        ↓
get_document_service 依赖 get_session
        ↓
get_session 从 Session Factory 创建 Session
        ↓
SqlAlchemyDocumentRepository(session)
        ↓
DocumentService(repository, uploads_dir)
        ↓
将 service 注入路由参数
```

请求结束后：

```text
路由返回或抛出异常
→ get_session 的 with 代码块退出
→ Session.close()
→ 连接归还 Engine 连接池
```

---

## 17. Create：POST 上传并创建文档

接口：

```http
POST /api/v1/documents
Content-Type: multipart/form-data
```

完整调用链：

```text
客户端上传文件
        ↓
FastAPI / python-multipart 解析 multipart
        ↓
UploadFile(filename, file, content_type)
        ↓
documents.upload_document()
        ↓
DocumentService.add_uploaded_document()
        ├── 清理文件名，阻止目录穿越
        ├── 校验扩展名 .txt/.md/.pdf
        ├── 分块读取并限制最大 10 MiB
        ├── 将文件写入 data/uploads
        └── Document.create() 生成 UUID、类型和时间
        ↓
SqlAlchemyDocumentRepository.add(document)
        ↓
Document → DocumentORM
        ↓
Session.add()
        ↓
Session.commit()
        ↓
PostgreSQL INSERT documents
        ↓
DocumentResponse.model_validate(document)
        ↓
HTTP 201 JSON
```

### 创建失败时的补偿

```text
文件已经写入
→ Repository/数据库写入失败
→ Service 删除刚写入的文件
→ Router 返回 409 或 500
```

文件系统和 PostgreSQL 不能共享普通事务，因此由 Service 显式补偿。

### 涉及文件

```text
api/routes/documents.py               upload_document
services/document_service.py          add_uploaded_document
models.py                              Document.create
repositories/sqlalchemy_repository.py add
db/models.py                           DocumentORM
schemas/documents.py                   DocumentResponse
```

---

## 18. Read List：GET 分页列表

接口：

```http
GET /api/v1/documents?offset=0&limit=20
```

调用链：

```text
FastAPI 校验 offset >= 0、1 <= limit <= 100
        ↓
documents.list_documents()
        ↓
DocumentService.list_documents_page(offset, limit)
        ├── repository.list_page(offset, limit)
        └── repository.count()
        ↓
PostgreSQL 执行两条查询
        ├── SELECT ... ORDER BY created_at DESC OFFSET ... LIMIT ...
        └── SELECT count(*) FROM documents
        ↓
DocumentORM 列表 → Document 列表
        ↓
DocumentListResponse
        ↓
HTTP 200 JSON
```

分页在 PostgreSQL 中完成，不会先把全表载入 Python。

---

## 19. Read Detail：GET 文档详情

接口：

```http
GET /api/v1/documents/{document_id}
```

调用链：

```text
路径参数 document_id
        ↓
documents.get_document()
        ↓
DocumentService.get_document(id)
        ↓
SqlAlchemyDocumentRepository.get_by_id(id)
        ├── str → UUID
        └── Session.get(DocumentORM, uuid)
        ↓
PostgreSQL 按主键 SELECT
        ↓
DocumentORM → Document
        ↓
DocumentResponse
        ↓
HTTP 200
```

不存在或 UUID 格式错误：

```text
DocumentNotFoundError
→ Router 捕获
→ HTTP 404
```

---

## 20. Update：PATCH 局部更新（预留练习）

接口已注册：

```http
PATCH /api/v1/documents/{document_id}
Content-Type: application/json
```

请求示例：

```json
{
  "name": "新名称.txt",
  "status": "ready"
}
```

目前已经完成的底层链：

```text
DocumentUpdateRequest
        ↓ 校验 name/status，拒绝空请求
service.update_document(id, name, document_status)
        ↓
Repository.get_by_id(id)
        ↓
dataclasses.replace() 创建更新后的 Document
        ↓
SqlAlchemyDocumentRepository.update(document)
        ↓
修改 Persistent DocumentORM 属性
        ↓
Session.commit()
        ↓
PostgreSQL UPDATE
```

目前缺少的是 Router 中间这一段：

```text
读取 payload
→ 调用 service.update_document(...)
→ 领域异常转换为 404/400/409
→ DocumentResponse.model_validate(updated_document)
```

因此当前 PATCH 返回 501，留给学习者实现。

---

## 21. Delete：DELETE 文件和元数据

接口：

```http
DELETE /api/v1/documents/{document_id}
```

调用链：

```text
documents.delete_document()
        ↓
DocumentService.delete_document(id)
        ↓
Repository.get_by_id(id)
        ↓
检查 stored_path 必须位于 uploads_dir 内
        ↓
原文件改名为隐藏的 .deleting 暂存文件
        ↓
SqlAlchemyDocumentRepository.delete(id)
        ├── Session.get()
        ├── Session.delete()
        └── Session.commit()
        ↓
PostgreSQL DELETE
        ↓
永久删除暂存文件
        ↓
HTTP 204 No Content
```

数据库删除失败时：

```text
Session.rollback()
→ Repository 抛出 StorageError
→ Service 把暂存文件恢复为原名
→ Router 返回 500
```

成功时 204 不包含响应体。

---

## 22. CRUD 五条链的横向对比

| 操作 | Router 输入 | Service 方法 | Repository 方法 | PostgreSQL | 文件系统 |
| --- | --- | --- | --- | --- | --- |
| Create | `UploadFile` | `add_uploaded_document` | `add` | `INSERT` | 写入文件 |
| Read List | `offset/limit` | `list_documents_page` | `list_page/count` | `SELECT` | 不操作 |
| Read Detail | `document_id` | `get_document` | `get_by_id` | `SELECT` | 不操作 |
| Update | ID + JSON | `update_document` | `update` | `UPDATE` | 当前不重命名实际文件 |
| Delete | `document_id` | `delete_document` | `delete` | `DELETE` | 暂存后删除 |

更新 `name` 只修改展示元数据，不会重命名 `stored_path` 对应的内部文件，这是有意设计：内部存储名称使用 UUID，避免用户名称变化影响文件定位。

---

## 23. CRUD 异常和状态码传播

```text
FastAPI/Pydantic 校验失败
→ 422

InvalidDocumentError
→ 400

DocumentConflictError
→ 409

DocumentNotFoundError
→ 404

StorageError
→ 500（对外隐藏底层数据库和路径细节）
```

成功状态：

```text
POST   → 201 Created
GET    → 200 OK
PATCH  → 完成后 200 OK
DELETE → 204 No Content
```

异常职责分层：

```text
Repository
→ 识别 SQLAlchemy/数据库异常，rollback，转换成领域异常

Service
→ 执行业务校验和文件补偿

Router
→ 把领域异常转换成 HTTP 状态码
```

---

## 24. 阶段 4～6 总依赖图

```mermaid
flowchart TD
    CLIENT["Client / Swagger / TestClient"] --> ROUTER["documents Router"]
    ROUTER --> REQUEST["FastAPI + Pydantic 校验"]
    ROUTER --> SERVICE["DocumentService"]

    SETTINGS["Settings"] --> UPLOADS["data/uploads"]
    SETTINGS --> SERVICE
    SERVICE --> UPLOADS

    DBSETTINGS["DatabaseSettings / .env"] --> ENGINE["Engine"]
    ENGINE --> FACTORY["Session Factory"]
    FACTORY --> SESSION["Request Session"]
    SESSION --> REPO["SqlAlchemyDocumentRepository"]
    REPO --> SERVICE
    REPO --> ORM["DocumentORM"]
    ORM --> PG[("PostgreSQL documents")]

    SERVICE --> DOMAIN["Document"]
    DOMAIN --> RESPONSE["DocumentResponse"]
    RESPONSE --> ROUTER

    BASE["Base.metadata"] --> ALEMBIC["Alembic env.py"]
    ORM --> BASE
    MIG1["Migration 01"] --> MIG2["Migration 02"]
    ALEMBIC --> MIG1
    MIG2 --> PG
```

要点：

- HTTP CRUD 通过 Router、Service 和 Repository 操作数据。
- Alembic 不参与每次 HTTP 请求，只在部署或开发时管理表结构。
- Engine 可以复用，Session 必须按请求创建和关闭。
- 文件系统操作集中在 Service，SQL 集中在 Repository。

---

## 25. 当前验收状态

```text
POST 上传             → 已完成
GET 分页列表          → 已完成
GET 详情              → 已完成
PATCH 局部更新        → Router 留给学习者，底层已完成
DELETE 文件和元数据   → 已完成
```

自动化验证：

```text
pytest：53 passed
Ruff：通过
mypy：通过
Alembic：20260813_02 (head)
```

完成 PATCH 路由和对应测试后，阶段 6 的完整 CRUD 才最终闭环。
