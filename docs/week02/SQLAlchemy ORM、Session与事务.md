# SQLAlchemy 原理、ORM、Session 与事务

## 1. 本阶段完成了什么

阶段 4 在不修改现有 CLI 和 FastAPI 存储方式的前提下，增加了一套 PostgreSQL 数据访问实现：

```text
Document 领域对象
    ↓
SqlAlchemyDocumentRepository
    ↓
SQLAlchemy Session
    ↓
Engine / psycopg
    ↓
PostgreSQL
```

本阶段已实现：

- 从 `.env` 读取开发库和测试库 URL。
- SQLAlchemy Declarative Base。
- `DocumentORM` 数据库模型。
- Engine 和 Session Factory 创建方法。
- Repository 抽象协议。
- SQLAlchemy Repository 的新增、列表、详情、更新和删除。
- ORM 对象与 `Document` 领域对象双向转换。
- 写操作的提交、异常回滚和数据库异常转换。
- 使用独立 PostgreSQL 测试库进行 Repository 集成测试。

正式开发库中仍没有手工创建 `documents` 表。阶段 5 将使用 Alembic 创建并管理正式表结构。

---

## 2. 为什么不让业务代码直接写 SQL

如果 Router 或 Service 直接执行数据库查询：

```text
Router → Session.query(...) → PostgreSQL
```

HTTP、业务规则和数据库细节就会混在一起。项目使用 Repository 隔离这些职责：

```text
Router → Service → DocumentRepository → PostgreSQL
```

Service 依赖 `DocumentRepository` 协议，而不是具体依赖 JSON 或 SQLAlchemy：

```python
class DocumentRepository(Protocol):
    def list_all(self) -> list[Document]: ...
    def get_by_id(self, document_id: str) -> Document: ...
    def add(self, document: Document) -> None: ...
    def delete(self, document_id: str) -> Document: ...
```

只要一个类具有这些方法，就符合协议，不需要显式继承。当前两个实现都可以交给 Service：

```text
JsonDocumentRepository          → 第一周文件存储
SqlAlchemyDocumentRepository    → 第二周 PostgreSQL 存储
```

这种设计让 API 后续切换 PostgreSQL 时，主要修改依赖组装，不必重写业务流程。

---

## 3. Engine、Connection 和 Session

### 3.1 Engine

Engine 是 SQLAlchemy 与数据库交互的入口，保存数据库方言、驱动和连接池配置：

```python
engine = create_engine(
    database_url,
    pool_pre_ping=True,
)
```

它不是一条永久连接。应用通常创建一个 Engine，并让它管理连接池。

`pool_pre_ping=True` 会在从连接池取出连接时检查连接是否仍然可用，适合数据库可能重启或连接长时间闲置的场景。

### 3.2 Connection

Connection 表示从 Engine 取得的一条数据库连接，可直接执行 SQL：

```python
with engine.connect() as connection:
    result = connection.execute(text("SELECT current_database()"))
```

本项目主要使用 ORM，所以日常 CRUD 通过 Session 完成；Connection 更适合连接验证或执行底层 SQL。

### 3.3 Session

Session 是 ORM 的工作单元，负责：

- 跟踪 ORM 对象状态。
- 将对象变化转换为 SQL。
- 控制事务。
- 在同一 Session 中维护对象身份。

它不是 Web 用户会话，也不是单纯的一条数据库连接。

### 3.4 Session Factory

项目没有创建一个永久共享的全局 Session，而是创建工厂：

```python
SessionFactory = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)
```

需要数据库操作时再创建 Session：

```python
with SessionFactory() as session:
    repository = SqlAlchemyDocumentRepository(session)
```

后续 FastAPI 通常每个请求使用一个独立 Session，并在请求结束时关闭：

```python
def get_session():
    with SessionFactory() as session:
        yield session
```

这样不同请求不会共享未提交状态，连接也能可靠归还连接池。

---

## 4. Declarative Base 和 ORM Model

### 4.1 Declarative Base

项目定义：

```python
class Base(DeclarativeBase):
    pass
```

所有 ORM 模型继承 Base。`Base.metadata` 汇总了表、字段、约束和索引信息，后续 Alembic 会读取它并比较 ORM 定义与数据库现状。

### 4.2 DocumentORM

`DocumentORM` 负责映射 `documents` 表：

```python
class DocumentORM(Base):
    __tablename__ = "documents"
```

属性通过 `Mapped[...]` 和 `mapped_column()` 声明：

```python
id: Mapped[UUID] = mapped_column(
    PostgreSQLUUID(as_uuid=True),
    primary_key=True,
)
```

这里有两层类型：

```text
Mapped[UUID]                       → Python 代码中的属性类型
PostgreSQLUUID(as_uuid=True)       → PostgreSQL 中的列类型和转换规则
```

### 4.3 ORM 模型不是领域模型

`DocumentORM` 和 `Document` 看起来字段接近，但用途不同：

| 对象 | 职责 | 是否依赖 SQLAlchemy |
| --- | --- | --- |
| `Document` | 表达业务中的文档 | 否 |
| `DocumentORM` | 映射数据库的一行 | 是 |

Repository 在边界处转换：

```text
写入：Document → DocumentORM → PostgreSQL
读取：PostgreSQL → DocumentORM → Document
```

这样 Service、CLI 和 API 不需要知道 Session、ORM 对象或 PostgreSQL UUID 类型。

---

## 5. Python 类型与 PostgreSQL 类型映射

| ORM Python 类型 | SQLAlchemy 类型 | PostgreSQL 类型 |
| --- | --- | --- |
| `UUID` | `PostgreSQLUUID(as_uuid=True)` | `UUID` |
| `str` | `String(255)` | `VARCHAR(255)` |
| `str` | `Text` | `TEXT` |
| `int` | `BigInteger` | `BIGINT` |
| `datetime` | `TIMESTAMP(timezone=True)` | `TIMESTAMPTZ` |

领域对象当前为了兼容 JSON，将 ID 和时间保存为字符串。Repository 写入时进行转换：

```text
str UUID       → uuid.UUID
ISO 8601 字符串 → datetime
```

查询后再转换回来。时间统一转换成 UTC ISO 8601 字符串，避免业务层依赖数据库会话时区。

---

## 6. 查询与 CRUD

### 6.1 新增

```python
row = self._from_domain(document)
self._session.add(row)
self._session.commit()
```

`add()` 只是将对象加入 Session 管理，真正执行 SQL 的时间可能是 `flush()` 或 `commit()`。

### 6.2 列表查询

SQLAlchemy 2.x 推荐使用 `select()`：

```python
statement = select(DocumentORM).order_by(
    DocumentORM.created_at,
    DocumentORM.id,
)
rows = session.scalars(statement).all()
```

- `select(DocumentORM)` 构造查询。
- `scalars()` 只取每行中的 ORM 对象。
- `all()` 得到列表。

### 6.3 按主键查询

```python
row = session.get(DocumentORM, document_uuid)
```

`Session.get()` 专门用于按主键查询。不存在时返回 `None`，Repository 再转换成 `DocumentNotFoundError`。

### 6.4 更新

```python
row.name = document.name
row.status = document.status
session.commit()
```

查询出来的 ORM 对象由 Session 跟踪。修改属性后，Session 会在 flush 时生成对应的 `UPDATE`。

### 6.5 删除

```python
session.delete(row)
session.commit()
```

Repository 在删除前先转换并保存领域对象，所以能够向 Service 返回被删除的文档信息。

---

## 7. flush、commit 和 rollback

这三个操作的区别非常重要。

### 7.1 flush

`flush()` 将 Session 中积累的变化发送到数据库，但通常仍处于当前事务中：

```text
Python ORM 变化
    ↓ flush
数据库已执行 INSERT/UPDATE/DELETE
    ↓ 尚未 commit
其他事务通常还看不到，当前事务仍可 rollback
```

SQLAlchemy 会在某些查询前或 `commit()` 时自动 flush，也可以手工调用以提前获得数据库生成的值或提前检查约束。

### 7.2 commit

`commit()` 会先完成必要的 flush，然后提交事务：

```text
flush → COMMIT → 修改持久化
```

提交后重新创建 Session 仍能查到数据，这正是集成测试验证的内容。

### 7.3 rollback

`rollback()` 撤销当前未提交事务，并清除 Session 的失败事务状态。

例如 `stored_path` 违反唯一约束时，PostgreSQL 拒绝写入。此时不仅要抛出异常，还必须执行：

```python
session.rollback()
```

否则 Session 会处于失败状态，后续查询会继续报错。测试验证了回滚后原数据仍存在，而且同一 Session 还能继续查询。

### 7.4 本阶段的事务边界

当前 Repository 的每个写方法都是一个独立事务：

```text
add()    → commit 或 rollback
update() → commit 或 rollback
delete() → commit 或 rollback
```

这种方式易于学习和测试。以后如果一个业务操作需要原子地修改多张表，事务边界可能上移到 Service 或专门的 Unit of Work，不能让每个 Repository 方法提前独立提交。

---

## 8. 异常分层

数据库驱动会抛出 `IntegrityError`、`OperationalError` 等异常。项目不应把这些底层异常直接传播给 API。

当前转换关系：

```text
查询不到数据
→ DocumentNotFoundError

唯一约束、检查约束等数据库错误
→ rollback
→ StorageError

其他 SQLAlchemy 数据库错误
→ rollback（写操作）
→ StorageError
```

日志使用 `logger.exception()` 时会记录堆栈，便于开发者排查；对外仍使用稳定的项目异常。

---

## 9. 配置与密码保护

`DatabaseSettings` 使用 `pydantic-settings` 读取：

```text
DATABASE_URL
TEST_DATABASE_URL
```

读取优先级包含系统环境变量和项目根目录 `.env`。字段启用了非空校验，配置缺失时应用会尽早失败，而不是运行到第一次数据库请求才报错。

真实 `.env` 已被 Git 忽略；可以提交的 `.env.example` 只包含 `CHANGE_ME`。

不要在日志或测试输出中打印完整数据库 URL，因为它包含密码。需要排查时只输出主机、端口和数据库名。

---

## 10. 集成测试如何隔离数据库

Repository 测试连接真实 PostgreSQL，因此属于集成测试。它们使用 `TEST_DATABASE_URL`，并有两层安全检查：

```text
测试数据库不能等于开发数据库
测试数据库名称必须以 _test 结尾
```

每个测试执行：

```text
drop_all（只清理测试库）
→ create_all（只创建测试所需表）
→ 执行测试
→ drop_all（清理测试库）
```

这里使用 `create_all/drop_all` 只为了让阶段 4 能在 Alembic 尚未初始化时独立验证 Repository。它只存在于测试夹具，不允许应用启动时调用。

从阶段 5 开始，正式开发库、服务器库以及更完整的迁移测试都由 Alembic 建表：

```text
应用代码：不调用 create_all
开发/服务器数据库：alembic upgrade head
阶段 4 临时测试夹具：Base.metadata.create_all
```

测试覆盖：

- 新增后重新创建 Session 仍能查询。
- 列表查询和对象转换。
- 按 ID 查询。
- 非法 UUID 和不存在 UUID 的领域异常。
- 更新和删除。
- 更新或删除不存在的文档。
- 唯一约束失败后的事务回滚。

---

## 11. 当前代码文件

```text
src/knowledge_assistant/
├── core/
│   └── config.py                    # 文件配置和数据库环境配置
├── db/
│   ├── __init__.py
│   ├── base.py                      # Declarative Base
│   ├── models.py                    # DocumentORM
│   └── session.py                   # Engine 和 Session Factory
├── repositories/
│   ├── base.py                      # DocumentRepository 协议
│   ├── json_repository.py           # JSON 实现
│   └── sqlalchemy_repository.py     # PostgreSQL 实现
└── services/
    └── document_service.py          # 依赖 Repository 协议

tests/
└── test_sqlalchemy_repository.py    # PostgreSQL 集成测试
```

---

## 12. 验证命令与结果

在项目根目录激活虚拟环境后运行：

```powershell
python -m pytest -q --basetemp=.pytest-tmp-full
python -m ruff check .
python -m mypy
```

本阶段完成时结果：

```text
pytest：42 passed
Ruff：All checks passed
mypy：Success: no issues found in 24 source files
```

其中 9 个测试是 PostgreSQL Repository 集成测试，原有 CLI、JSON Repository 和 FastAPI 测试仍然通过。

---

## 13. 阶段 4 完成标准

- [x] 安装 SQLAlchemy、psycopg、pydantic-settings 和 Alembic。
- [x] 建立 Declarative Base。
- [x] 定义 `DocumentORM` 和数据库约束。
- [x] 创建 Engine 和 Session Factory。
- [x] 实现 ORM 与领域对象双向转换。
- [x] 实现数据库 Repository CRUD。
- [x] 写操作包含 commit 和异常 rollback。
- [x] Repository 不向 Service 返回 ORM 对象。
- [x] 集成测试使用独立测试数据库。
- [x] 原有功能和质量检查全部通过。

阶段 4 已经可以独立验收。下一步是阶段 5：初始化 Alembic，用第一条迁移在开发库创建 `documents` 表，再用第二条迁移添加 `updated_at`。

---

## 14. SQLAlchemy 的整体分层

SQLAlchemy 不是只有 ORM，它主要包含两层：

```text
ORM
├── Declarative Mapping
├── Session / Unit of Work
├── Relationship
└── ORM 查询和对象加载
        ↓ 建立在其上
Core
├── Engine / Connection
├── SQL Expression Language
├── Table / Column / MetaData
└── 数据库方言与类型系统
        ↓
DBAPI 驱动 psycopg
        ↓
PostgreSQL
```

### 14.1 Core

Core 使用 SQL 表达式和连接操作数据库，不要求把结果映射成业务类：

```python
from sqlalchemy import MetaData, Table, select

metadata = MetaData()
documents = Table("documents", metadata, autoload_with=engine)

with engine.connect() as connection:
    rows = connection.execute(
        select(documents).where(documents.c.status == "ready")
    ).mappings().all()
```

### 14.2 ORM

ORM 把表映射为 Python 类：

```python
statement = select(DocumentORM).where(DocumentORM.status == "ready")
documents = session.scalars(statement).all()
```

ORM 最终仍会生成 SQL，不会让关系数据库变成普通 Python 集合。理解 SQL、索引和事务仍然必要。

### 14.3 什么时候使用哪一层

| 场景 | 更适合 |
| --- | --- |
| 常规领域实体 CRUD | ORM |
| 动态报表、复杂聚合 | Core 或 ORM + Core 表达式 |
| 批量更新/删除 | SQL Expression DML |
| 迁移脚本 | Alembic Operations + SQLAlchemy Core 类型 |
| 执行数据库特有 SQL | `text()` 或方言 API |

实际项目可以同时使用 Core 和 ORM，不必二选一。

---

## 15. Declarative Mapping 深入理解

### 15.1 `Mapped` 与 `mapped_column`

SQLAlchemy 2.x 的类型化声明：

```python
name: Mapped[str] = mapped_column(String(255), nullable=False)
```

包含两类信息：

```text
Mapped[str]                 → Python 静态类型和 ORM 属性
String(255), nullable=False → 数据库列结构
```

常见推断：

```python
description: Mapped[str | None]
```

类型中的 `None` 通常能帮助推断列可空，但重要数据库结构建议仍显式声明，便于阅读。

### 15.2 Python 默认值与数据库默认值

```python
status: Mapped[str] = mapped_column(
    default="uploaded",
    server_default="uploaded",
)
```

区别：

| 配置 | 在哪里执行 | 适用情况 |
| --- | --- | --- |
| `default` | SQLAlchemy 生成 INSERT 时 | 通过当前 ORM 写入 |
| `server_default` | PostgreSQL | 任何客户端未提供该列时 |

只有 Python `default` 时，其他客户端直接 INSERT 可能得不到默认值。只有数据库默认值时，SQLAlchemy 需要在 INSERT 后取得服务器生成结果。

### 15.3 `onupdate` 与服务器更新逻辑

```python
updated_at: Mapped[datetime] = mapped_column(
    server_default=func.now(),
    onupdate=func.now(),
)
```

`onupdate` 是 SQLAlchemy 在自己生成 UPDATE 时加入表达式，不代表 PostgreSQL 会对所有来源的 UPDATE 自动更新时间。

如果要求任何数据库客户端更新都刷新时间，需要数据库触发器；如果只允许应用通过 ORM 更新，`onupdate` 通常更简单。

### 15.4 MetaData

`Base.metadata` 包含 SQLAlchemy 已加载的所有表定义：

```python
print(Base.metadata.tables.keys())
```

它是 Python 内存中的结构说明，不是真实数据库。Alembic 使用它与数据库反射结果比较。

### 15.5 命名约定

大型项目通常为约束设置统一命名约定：

```python
from sqlalchemy import MetaData

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)
```

稳定名称让迁移、错误日志和跨数据库处理更可预测。本项目目前在模型和迁移中显式命名关键约束。

---

## 16. ORM 对象的五种状态

Session 不只是执行 SQL，还会跟踪对象状态。

### 16.1 Transient：临时状态

刚创建、还没加入 Session：

```python
row = DocumentORM(...)
```

它只有 Python 属性，不对应当前 Session 中的持久化身份。

### 16.2 Pending：待持久化

```python
session.add(row)
```

对象进入 Pending，通常尚未执行 INSERT。

### 16.3 Persistent：持久化

执行 flush 后，对象已对应数据库行并由 Session 跟踪：

```python
session.flush()
```

修改 Persistent 对象的属性，Session 会记录变化，并在下次 flush 生成 UPDATE。

### 16.4 Deleted：待删除

```python
session.delete(row)
```

对象被标记为删除，flush 时发送 DELETE。

### 16.5 Detached：游离状态

Session 关闭或对象被 expunge 后，对象不再关联 Session。已经加载的普通属性仍可能读取，但未加载的延迟属性不能再自动查询。

查看状态：

```python
from sqlalchemy import inspect

state = inspect(row)
print(state.transient, state.pending, state.persistent, state.detached)
```

对象状态转换：

```text
Transient --add--> Pending --flush--> Persistent
Persistent --delete--> Deleted --commit--> Detached
Persistent --close/expunge--> Detached
```

---

## 17. Identity Map：为什么同一个主键常得到同一个对象

Session 内部维护 Identity Map，以“映射类 + 主键”作为对象身份。

```python
first = session.get(DocumentORM, document_id)
second = session.get(DocumentORM, document_id)

assert first is second
```

在同一个 Session 中，如果对象已经存在且未过期，第二次获取可能直接使用同一个 Python 对象，而不是重复构造。

作用：

- 同一行不会在一个 Session 中出现多个互相矛盾的对象副本。
- 便于 Unit of Work 汇总变化。
- 部分主键查询可以减少数据库访问。

Identity Map 不是通用查询缓存：

- 普通 `select()` 仍然可能发送 SQL。
- 不跨 Session 缓存。
- 不代替 Redis 等应用缓存。
- 数据被其他事务修改后，当前对象可能需要 refresh/expire 才能重新读取。

---

## 18. Unit of Work：Session 如何统一生成 SQL

Unit of Work 会收集当前 Session 中对象的新增、修改和删除，在 flush 时按依赖顺序生成 SQL：

```python
document = DocumentORM(...)
session.add(document)

document.status = "processing"

session.delete(other_document)
session.flush()
```

它会综合判断需要执行哪些 INSERT、UPDATE 和 DELETE，而不是每改一个属性立刻发送 SQL。

查看待处理集合：

```python
print(session.new)
print(session.dirty)
print(session.deleted)
```

这也解释了为什么 Session 不应被多个并发请求共享：不同请求的对象状态和事务会混到同一个工作单元中。

---

## 19. Autobegin、Autoflush 和 Expire

### 19.1 Autobegin

SQLAlchemy 2.x 的 Session 在需要数据库操作时自动开始事务：

```python
session = SessionFactory()
document = session.get(DocumentORM, document_id)
```

即使只是 SELECT，PostgreSQL 连接通常也进入事务，直到 commit、rollback 或 close。因此“只查不写”也应及时结束 Session。

### 19.2 Autoflush

默认情况下，在执行某些查询前，Session 可能自动 flush 未提交变化：

```python
row = DocumentORM(...)
session.add(row)

# 执行 SELECT 前可能先 INSERT
result = session.scalars(select(DocumentORM)).all()
```

临时禁止：

```python
with session.no_autoflush:
    result = session.scalars(statement).all()
```

`no_autoflush` 只应解决明确的对象尚未准备完整问题，不应成为隐藏错误的默认做法。

### 19.3 Expire on commit

默认 `expire_on_commit=True` 时，commit 后对象属性会被标记过期，下次访问可能重新查询数据库。

本项目使用：

```python
expire_on_commit=False
```

便于 Repository 提交后继续把 ORM 对象转换为领域对象，而不触发额外查询。

代价是对象可能保留提交时的旧值。如果需要最新数据库状态，可调用：

```python
session.refresh(row)
session.expire(row)
session.expire_all()
```

---

## 20. 推荐的事务上下文写法

### 20.1 Engine + Connection

自动提交或回滚：

```python
with engine.begin() as connection:
    connection.execute(statement)
```

代码块正常结束时提交，异常时回滚。

### 20.2 Session 事务

```python
with SessionFactory() as session:
    with session.begin():
        session.add(document)
        session.add(other_document)
```

也可以合并：

```python
with SessionFactory.begin() as session:
    session.add(document)
```

这种结构把 commit/rollback 交给上下文管理器，减少忘记回滚的风险。

### 20.3 SAVEPOINT / Nested Transaction

```python
with session.begin():
    session.add(first)

    try:
        with session.begin_nested():
            session.add(possibly_duplicate)
    except IntegrityError:
        pass
```

`begin_nested()` 在支持的数据库中使用 SAVEPOINT，可以回滚局部操作，而不一定放弃外层整个事务。

### 20.4 当前 Repository 的方式

当前项目为了便于学习，让 `add/update/delete` 各自 commit/rollback。它适合单 Repository 简单操作，但如果未来一个业务需要：

```text
新增 document
新增多个 chunk
新增 processing_job
```

就应让它们处于同一个外层事务，而不是每个 Repository 方法提前 commit。届时可以引入 Service 事务边界或 Unit of Work 模式。

---

## 21. SQLAlchemy 2.x 常用查询 API

### 21.1 基本查询

```python
statement = select(DocumentORM)
rows = session.scalars(statement).all()
```

### 21.2 WHERE

```python
statement = select(DocumentORM).where(
    DocumentORM.status == "ready",
    DocumentORM.file_size > 0,
)
```

常用条件：

```python
DocumentORM.name.like("%.pdf")
DocumentORM.name.ilike("%guide%")
DocumentORM.status.in_(["ready", "failed"])
DocumentORM.updated_at.is_(None)
DocumentORM.file_size.between(1, 1024)
```

### 21.3 AND、OR、NOT

```python
from sqlalchemy import and_, not_, or_

statement = select(DocumentORM).where(
    or_(
        DocumentORM.status == "ready",
        and_(
            DocumentORM.status == "failed",
            DocumentORM.file_size > 0,
        ),
    )
)
```

### 21.4 排序和分页

```python
statement = (
    select(DocumentORM)
    .order_by(DocumentORM.created_at.desc(), DocumentORM.id)
    .offset(offset)
    .limit(limit)
)
```

大偏移量分页会越来越慢。数据量大时可使用基于上次排序键的 Keyset/Cursor Pagination：

```python
where(DocumentORM.created_at < last_created_at)
```

### 21.5 返回单个结果

```python
session.scalar(statement)             # 第一列第一个值或 None
session.scalars(statement).first()    # 第一个 ORM 对象或 None
session.scalars(statement).one()      # 必须恰好一个，否则异常
session.scalars(statement).one_or_none()
```

按主键优先：

```python
session.get(DocumentORM, primary_key)
```

### 21.6 聚合

```python
from sqlalchemy import func

count = session.scalar(
    select(func.count()).select_from(DocumentORM)
)
```

按状态统计：

```python
statement = (
    select(DocumentORM.status, func.count(DocumentORM.id))
    .group_by(DocumentORM.status)
)

rows = session.execute(statement).all()
```

### 21.7 EXISTS

```python
exists_statement = select(
    select(DocumentORM.id)
    .where(DocumentORM.stored_path == path)
    .exists()
)

exists = session.scalar(exists_statement)
```

### 21.8 原生 SQL

```python
from sqlalchemy import text

result = session.execute(
    text("SELECT * FROM documents WHERE status = :status"),
    {"status": "ready"},
)
```

使用绑定参数，不要用字符串拼接用户输入，避免 SQL 注入。

---

## 22. INSERT、UPDATE、DELETE 的常用形式

### 22.1 ORM 单对象新增

```python
session.add(document)
session.commit()
```

### 22.2 多对象新增

```python
session.add_all([first, second, third])
session.commit()
```

### 22.3 SQL Expression UPDATE

```python
from sqlalchemy import update

statement = (
    update(DocumentORM)
    .where(DocumentORM.status == "uploaded")
    .values(status="processing")
)
session.execute(statement)
session.commit()
```

它适合批量更新，不需要逐个加载 ORM 对象。要理解它与 Session 中已加载对象的同步问题。

### 22.4 DELETE

```python
from sqlalchemy import delete

statement = delete(DocumentORM).where(DocumentORM.status == "failed")
session.execute(statement)
session.commit()
```

批量 DML 绕过逐对象业务逻辑和部分 ORM 级联，应谨慎使用。

### 22.5 PostgreSQL UPSERT

```python
from sqlalchemy.dialects.postgresql import insert

statement = insert(DocumentORM).values(...)
statement = statement.on_conflict_do_update(
    index_elements=[DocumentORM.id],
    set_={"status": statement.excluded.status},
)
session.execute(statement)
```

UPSERT 很方便，但要先定义“发生冲突时覆盖哪些字段”以及是否可能掩盖重复数据错误。

---

## 23. Relationship 与外键映射

以后增加切片模型时：

```python
class DocumentORM(Base):
    chunks: Mapped[list["DocumentChunkORM"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentChunkORM(Base):
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    document: Mapped[DocumentORM] = relationship(back_populates="chunks")
```

两个层面的级联要分清：

```text
ORM cascade        → Session 如何处理关联对象
数据库 ON DELETE   → PostgreSQL 如何处理外键引用
```

二者可以配合，但不是同一件事。

---

## 24. Lazy Loading、N+1 和加载策略

访问未加载的关系属性时，ORM 可能发出额外 SQL：

```python
documents = session.scalars(select(DocumentORM)).all()

for document in documents:
    print(document.chunks)  # 每个 document 可能再查一次
```

如果查询 100 个文档后又产生 100 次切片查询，就是 N+1 问题。

常见策略：

### 24.1 `selectinload`

```python
from sqlalchemy.orm import selectinload

statement = select(DocumentORM).options(
    selectinload(DocumentORM.chunks)
)
```

先查文档，再用一条或少量 IN 查询批量加载关联集合，通常适合一对多。

### 24.2 `joinedload`

```python
from sqlalchemy.orm import joinedload

statement = select(DocumentORM).options(
    joinedload(DocumentORM.chunks)
)
```

通过 JOIN 一次取得数据，但一对多会造成父行重复，常需要：

```python
session.scalars(statement).unique().all()
```

### 24.3 `raiseload`

在不希望意外发出额外 SQL 的场景，可以让未显式加载的关系直接报错，从测试阶段发现 N+1。

加载策略没有统一最优解，需要根据关系基数、查询范围和返回数据量选择。

---

## 25. 连接池与 Engine 配置

Engine 默认通常使用连接池。一次 Session 需要访问数据库时，从池中取连接，事务结束且 Session 关闭后归还。

常用参数：

```python
engine = create_engine(
    database_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
```

| 参数 | 含义 |
| --- | --- |
| `pool_size` | 常驻连接数量上限附近的基础池大小 |
| `max_overflow` | 高峰时允许临时新增连接数 |
| `pool_timeout` | 等待连接的最长时间 |
| `pool_recycle` | 达到一定年龄后替换连接 |
| `pool_pre_ping` | 取连接时检查连接是否存活 |

不要盲目把池设置很大：

```text
应用实例数 × 每实例连接池上限
```

必须小于数据库可承受连接数，并为管理、迁移和其他服务保留空间。

调试 SQL：

```python
create_engine(database_url, echo=True)
```

生产环境不要长期打印包含敏感参数或海量 SQL 的详细日志。

---

## 26. Session 并发安全与 FastAPI 生命周期

Session 是可变、有状态对象，不应在多个线程或并发任务间共享。

同步 FastAPI 常见依赖：

```python
def get_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session
```

调用链：

```text
一个 HTTP 请求
→ 创建一个 Session
→ Router/Service/Repository 共用该 Session
→ 请求完成
→ close，连接归还池
```

不要这样做：

```python
global_session = SessionFactory()
```

全局永久 Session 会导致：

- 不同请求共享事务和对象状态。
- 连接长时间占用。
- 失败状态污染后续请求。
- 并发安全问题。

### 同步与异步不能混用

当前项目使用同步 `Session` 和 psycopg 同步连接。异步版本需要：

```text
create_async_engine
AsyncSession
async_sessionmaker
await session.execute(...)
```

不要仅把路由改成 `async def` 就认为数据库访问自动异步。同步驱动在事件循环中仍可能阻塞。

---

## 27. 并发更新策略

### 27.1 悲观锁

```python
statement = (
    select(DocumentORM)
    .where(DocumentORM.id == document_id)
    .with_for_update()
)
row = session.scalar(statement)
```

它让 PostgreSQL 锁定匹配行，适合确实需要串行修改的关键流程。事务必须尽量短。

### 27.2 乐观锁

增加版本号：

```python
version_id: Mapped[int] = mapped_column(nullable=False, default=1)

__mapper_args__ = {
    "version_id_col": version_id,
}
```

更新时 SQLAlchemy 会把旧版本号加入 WHERE。如果另一事务已经更新，受影响行数为 0，就能检测丢失更新。

适合冲突较少、不能长期锁行的场景。捕获冲突后应让调用者刷新数据或重试，而不是静默覆盖。

---

## 28. 异常分类与处理原则

常见 SQLAlchemy 异常：

| 异常 | 常见原因 |
| --- | --- |
| `IntegrityError` | 唯一、外键、非空、CHECK 约束失败 |
| `OperationalError` | 连接断开、数据库不可用、超时等 |
| `ProgrammingError` | SQL 或表列名称错误 |
| `DataError` | 数据格式或范围不符合数据库要求 |
| `NoResultFound` | `.one()` 等要求结果但不存在 |
| `MultipleResultsFound` | 期望一个结果但返回多个 |
| `PendingRollbackError` | 上次事务失败后没有 rollback |

处理原则：

```text
记录底层异常和堆栈供开发者排查
→ 写事务失败立即 rollback
→ 转换成稳定的项目领域异常
→ 不向 API 泄露数据库地址、SQL 和密码
```

不是所有错误都应该自动重试：

- 唯一约束失败通常是业务冲突，重试无用。
- 短暂网络错误可能重试，但要保证操作幂等。
- 序列化失败或死锁可以重试整个事务，而不是只重试最后一条 SQL。

---

## 29. Repository 与 Unit of Work 的边界选择

当前 Repository 自己 commit，调用简单：

```python
repository.add(document)
```

但跨多个 Repository 的业务会遇到问题：

```text
document_repository.add() 已提交
chunk_repository.add_many() 失败
→ 文档存在但切片不完整
```

更完整的 Unit of Work 可以统一事务：

```python
with unit_of_work:
    unit_of_work.documents.add(document)
    unit_of_work.chunks.add_many(chunks)
    unit_of_work.commit()
```

当前学习阶段先保持简单。未来出现真正的多表原子业务时再重构，避免过早引入抽象。

---

## 30. 数据库测试的三种层次

### 30.1 纯单元测试

使用假 Repository，测试 Service 业务逻辑：

```text
快、不依赖数据库，但不能发现 SQL 和 PostgreSQL 类型问题
```

### 30.2 Repository 集成测试

使用真实 PostgreSQL 测试库：

```text
能验证约束、事务、SQL 和驱动行为，速度稍慢
```

本项目 `test_sqlalchemy_repository.py` 属于这一层。

### 30.3 API 端到端测试

```text
HTTP → FastAPI → Service → Repository → PostgreSQL
```

它覆盖整条链，但定位失败原因更困难，不应替代较低层测试。

测试隔离常见方案：

- 每个测试清空表。
- 每个测试使用事务并回滚。
- 每个测试使用独立 Schema。
- 每次测试运行启动临时 PostgreSQL 容器。

如果业务代码内部会 commit，外层事务回滚方案需要 SAVEPOINT 或专门 Session 绑定策略，不能简单假设最后 rollback 就一定隔离。

---

## 31. 常用调试与检查方法

查看生成的 SQL，但不执行：

```python
statement = select(DocumentORM).where(DocumentORM.status == "ready")
print(statement.compile(compile_kwargs={"literal_binds": True}))
```

`literal_binds` 仅用于调试，复杂类型不一定都能安全内联，也不要把包含敏感数据的结果写入日志。

检查对象状态：

```python
from sqlalchemy import inspect

state = inspect(row)
print(state.pending, state.persistent, state.detached)
```

检查 Session 状态：

```python
print(session.in_transaction())
print(session.new)
print(session.dirty)
print(session.deleted)
```

临时开启 Engine 日志：

```python
engine = create_engine(database_url, echo=True)
```

数据库侧再配合：

```sql
SELECT * FROM pg_stat_activity;
EXPLAIN (ANALYZE, BUFFERS) ...;
```

应用日志说明“哪个业务触发了查询”，数据库工具说明“SQL 如何执行”，两边结合才容易定位问题。

---

## 32. 常见错误清单

### 32.1 把 Session 当作全局单例

错误原因：事务和对象状态跨请求污染。

### 32.2 捕获数据库异常后忘记 rollback

结果：后续操作出现 `PendingRollbackError`。

### 32.3 在循环中触发 Lazy Loading

结果：N+1 查询。

### 32.4 使用 `create_all()` 管理生产结构

`create_all()` 只能创建缺失表，不能可靠表达历史演进、回退和数据迁移。正式结构使用 Alembic。

### 32.5 ORM 字段改了但没迁移

Python 模型与真实表不一致，运行时会出现列不存在或约束不一致。

### 32.6 返回 ORM 对象到所有业务层

会让业务逻辑依赖 Session 生命周期，并可能在序列化时意外触发 SQL。当前 Repository 返回独立 `Document`。

### 32.7 对所有场景都 commit

查询通常不需要 commit；跨多步骤业务又不能过早 commit。事务边界应与业务原子性一致。

### 32.8 误以为 ORM 会自动优化 SQL

ORM 负责构造和映射，不会自动为业务创建最佳索引，也不会自动消除 N+1。仍需检查 SQL 和执行计划。

---

## 33. SQLAlchemy 常用方法速查

| 类别 | 方法 | 作用 |
| --- | --- | --- |
| Engine | `create_engine()` | 创建同步 Engine |
| Engine | `engine.connect()` | 获取 Connection |
| Engine | `engine.begin()` | 开启自动提交/回滚事务块 |
| Session | `sessionmaker()` | 创建 Session 工厂 |
| Session | `add()/add_all()` | 将对象加入工作单元 |
| Session | `get()` | 按主键查询 |
| Session | `execute()` | 执行 SQL 表达式 |
| Session | `scalar()` | 返回一个标量值 |
| Session | `scalars()` | 返回一列标量/ORM 对象流 |
| Session | `flush()` | 将变化发送数据库但不提交 |
| Session | `refresh()` | 从数据库刷新对象 |
| Session | `expire()` | 标记属性下次访问时重新加载 |
| Session | `delete()` | 标记对象删除 |
| Session | `commit()` | 提交事务 |
| Session | `rollback()` | 回滚事务并恢复可用状态 |
| Session | `close()` | 释放资源并归还连接 |
| Query | `select()` | 构造 SELECT |
| Query | `where()` | 添加过滤条件 |
| Query | `order_by()` | 排序 |
| Query | `limit()/offset()` | 分页 |
| Query | `join()` | 构造 JOIN |
| Loading | `selectinload()` | 批量加载关联 |
| Loading | `joinedload()` | JOIN 加载关联 |

官方延伸阅读：

- [SQLAlchemy 2.0 官方文档](https://docs.sqlalchemy.org/en/20/)
- [Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [ORM Querying Guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/index.html)
- [Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
