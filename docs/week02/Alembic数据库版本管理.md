# Alembic 原理、常用方法与数据库版本管理

## 1. 为什么需要 Alembic

SQLAlchemy ORM 只能描述应用期望的表结构，修改 Python 模型不会自动、可靠地修改已有数据库。

如果依靠手工 SQL 管理表结构，很容易出现：

```text
开发者 A 的本地数据库 → 有 updated_at
开发者 B 的本地数据库 → 没有 updated_at
服务器数据库           → 字段类型又不一样
```

Alembic 把每次数据库结构变化保存成可以进入 Git 的迁移文件：

```text
ORM 最终结构
    ↓ 设计/比较
迁移 01：创建 documents
    ↓
迁移 02：添加 updated_at
    ↓
本地、测试、服务器按相同顺序执行
```

它管理的是数据库结构版本，不是业务数据备份工具。

---

## 2. 本项目的迁移结构

```text
knowledge-assistant/
├── alembic.ini
└── migrations/
    ├── env.py
    ├── script.py.mako
    ├── README
    └── versions/
        ├── 20260813_01_create_documents_table.py
        └── 20260813_02_add_updated_at_to_documents.py
```

### `alembic.ini`

保存 Alembic 的通用配置，例如迁移目录、Python 导入路径和日志配置。

项目没有在这里保存真实数据库密码：

```ini
sqlalchemy.url = driver://unused
```

### `migrations/env.py`

这是 Alembic 每次执行命令时加载的运行环境。它完成三件关键工作：

1. 从 `.env` 读取 `DATABASE_URL`。
2. 导入全部 ORM 模型。
3. 将 `Base.metadata` 设置为 `target_metadata`。

```python
settings = DatabaseSettings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata
```

密码包含 `%` 时，写入 Alembic 配置前需要转义成 `%%`，因为配置解析器把 `%` 用于插值。

### `script.py.mako`

这是以后执行 `alembic revision` 时使用的迁移脚本模板。

### `versions`

每个文件代表一次结构变更。迁移文件需要提交 Git，并且已经在共享环境执行过的迁移原则上不能随意重写。

---

## 3. Revision、Head、Upgrade 和 Downgrade

### 3.1 Revision

Revision 是一个数据库结构版本。本项目当前迁移链：

```text
base
  ↓
20260813_01  create_documents_table
  ↓
20260813_02  add_updated_at_to_documents（head）
```

每个迁移文件包含：

```python
revision = "20260813_02"
down_revision = "20260813_01"
```

- `revision` 是当前版本 ID。
- `down_revision` 指向父版本。
- 第一条迁移的 `down_revision` 是 `None`。

### 3.2 Head

Head 是迁移链当前最新版本。本项目当前为：

```text
20260813_02
```

### 3.3 Upgrade

Upgrade 向前应用迁移：

```powershell
alembic upgrade head
```

空库会依次执行 01 和 02；已经在 01 的数据库只执行 02；已经在 head 时不会重复执行。

### 3.4 Downgrade

Downgrade 回退结构：

```powershell
alembic downgrade -1
```

`-1` 表示回退一个版本。本项目从 head 回退后会删除 `updated_at`，但保留 `documents` 表。

回退到完全没有业务表：

```powershell
alembic downgrade base
```

回退可能删除列、表和其中的数据。在真实环境执行前必须评估数据风险并做好备份。

---

## 4. Alembic 如何知道数据库版本

第一次升级时，Alembic 会创建：

```text
alembic_version
```

它不是业务表，只记录当前 Revision：

```sql
SELECT version_num FROM alembic_version;
```

当前结果：

```text
20260813_02
```

因此 Alembic 不需要猜测哪些迁移执行过，而是根据版本表和迁移链计算下一步。

不要手工修改 `alembic_version`，否则记录版本可能与真实表结构不一致。

---

## 5. 第一条迁移：创建 documents

第一条迁移的 `upgrade()` 创建：

- UUID 主键。
- 文档名称、路径、类型和大小。
- 状态及默认值。
- 带时区创建时间。
- 非空、唯一和检查约束。
- `status + created_at DESC` 组合索引。

核心调用：

```python
op.create_table(...)
op.create_index(...)
```

对应的 `downgrade()` 按反方向执行：

```python
op.drop_index(...)
op.drop_table("documents")
```

先删除索引再删除表，使回退意图清晰。

---

## 6. 第二条迁移：添加 updated_at

第二条迁移用于证明已有数据库可以增量演进：

```python
op.add_column(
    "documents",
    sa.Column(
        "updated_at",
        postgresql.TIMESTAMP(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    ),
)
```

为什么设置数据库默认值：

- 新插入记录没有显式提供时会得到当前时间。
- 如果表中已经有旧数据，添加非空列时旧行也能获得初始值。

对应回退：

```python
op.drop_column("documents", "updated_at")
```

ORM 中的 `onupdate=func.now()` 会让通过 SQLAlchemy ORM 执行更新时刷新该列；数据库自身不会仅凭默认值在每次 UPDATE 时自动刷新它。

---

## 7. target_metadata 的作用

`target_metadata` 指向：

```python
Base.metadata
```

它包含 SQLAlchemy 已知的表、列、约束和索引，是 ORM 的结构快照。

当运行：

```powershell
alembic revision --autogenerate -m "说明"
```

Alembic 会比较：

```text
当前数据库结构
        ↕
Base.metadata 期望结构
```

并生成差异候选迁移。

如果忘记导入 `DocumentORM`，该模型不会注册到 `Base.metadata`，自动生成可能错误地认为没有 `documents` 表。因此 `env.py` 显式导入 `knowledge_assistant.db.models`。

---

## 8. 为什么自动生成后仍要人工检查

Autogenerate 只能根据结构差异提出代码，不能完整理解业务意图。生成后至少检查：

- 升级和回退方向是否正确。
- 是否错误删除表或列。
- 字段是否允许为空。
- 默认值是在 Python 端还是数据库端。
- 约束和索引名称是否稳定。
- 修改类型是否会丢失数据。
- 新增非空列时已有数据怎么处理。
- Downgrade 是否存在不可逆的数据损失。

本项目的两条迁移经过人工整理，使用明确的约束名和可解释的降级操作。

---

## 9. 常用命令

查看当前数据库版本：

```powershell
alembic current
```

查看迁移历史：

```powershell
alembic history --verbose
```

升级到最新版本：

```powershell
alembic upgrade head
```

回退一次：

```powershell
alembic downgrade -1
```

再次升级：

```powershell
alembic upgrade head
```

检查 ORM 与数据库是否还有未生成差异：

```powershell
alembic check
```

只输出迁移 SQL，不执行数据库修改：

```powershell
alembic upgrade head --sql
```

创建下一条自动生成迁移：

```powershell
alembic revision --autogenerate -m "change description"
```

不要在没有检查生成文件的情况下直接执行新迁移。

---

## 10. 本次实际演练记录

### 10.1 空库状态

执行前开发库没有业务表：

```text
[]
```

### 10.2 从空库升级到 head

```powershell
alembic upgrade head
```

执行顺序：

```text
base → 20260813_01 → 20260813_02
```

得到：

```text
alembic_version
documents
```

`documents` 包含：

```text
id, name, original_path, stored_path, file_type,
file_size, status, created_at, updated_at
```

### 10.3 回退一次

```powershell
alembic downgrade -1
```

版本变为：

```text
20260813_01
```

`updated_at` 被移除，其他字段和表仍存在。

### 10.4 再次升级

```powershell
alembic upgrade head
```

版本重新变为：

```text
20260813_02 (head)
```

### 10.5 一致性检查

```powershell
alembic check
```

结果：

```text
No new upgrade operations detected.
```

说明当前 ORM 元数据与开发数据库的最新结构一致。

---

## 11. 自动化迁移测试

`tests/test_migrations.py` 使用独立的 `knowledge_assistant_test`，并强制检查：

```text
测试库不等于开发库
测试库名必须以 _test 结尾
```

测试覆盖：

- 第一条迁移创建第一版表。
- 第一版没有 `updated_at`。
- 第二条迁移添加非空 `updated_at` 和默认值。
- 第二条迁移能够回退。
- 回退后能够再次升级。

测试开始前和结束后都会执行：

```text
alembic downgrade base
→ 删除测试库中已经清空的 alembic_version 管理表
```

所以测试库不会遗留 `documents` 或 `alembic_version` 表。

---

## 12. 开发库、测试库和服务器的使用方式

```text
开发库 knowledge_assistant_dev
→ 手工执行 alembic upgrade head
→ 保留最新表结构，供 API 联调

测试库 knowledge_assistant_test
→ 自动化测试临时升级和回退
→ 测试结束清空

服务器 PostgreSQL 17
→ 拉取同一份 Git 迁移文件
→ 执行 alembic upgrade head
```

服务器不需要复制本地数据库文件，也不需要手工重建表。只要配置正确的 `DATABASE_URL` 并执行同一迁移链，就能得到一致结构。

---

## 13. 安全注意事项

- 运行命令前确认 `.env` 指向哪个数据库。
- 不把真实密码写入 `alembic.ini` 或迁移文件。
- 不在生产数据库随意执行 `downgrade`。
- 删除列或表之前先确认数据备份和恢复方案。
- 迁移文件进入共享环境后不要随意修改历史。
- 不使用 `Base.metadata.create_all()` 代替正式迁移。
- 先在测试库演练，再应用到服务器。

---

## 14. 阶段 5 验收结论

- [x] 初始化 Alembic 配置。
- [x] 从 `.env` 安全读取连接地址。
- [x] 配置 `target_metadata`。
- [x] 创建第一条建表迁移。
- [x] 创建第二条 `updated_at` 迁移。
- [x] 从空开发库升级到 head。
- [x] 回退一次并确认字段移除。
- [x] 再次升级到 head。
- [x] 确认 ORM 与数据库结构一致。
- [x] 编写独立测试库迁移测试。
- [x] 编写 Alembic 学习文档。

阶段 5 完成后，开发数据库已经可以由 SQLAlchemy Repository 正式使用。下一阶段可以将 FastAPI 的依赖从 JSON Repository 切换为 SQLAlchemy Repository，并实现 HTTP 上传、修改和删除接口。

---

## 15. Alembic、SQLAlchemy 和 PostgreSQL 的关系

三者不是同一种工具：

```text
PostgreSQL
→ 真正保存数据和表结构的数据库服务器

SQLAlchemy
→ Python 中描述表、构造 SQL、管理连接和 ORM 对象

Alembic
→ 使用 SQLAlchemy 的结构信息和类型系统，管理数据库结构版本
```

完整关系：

```text
DocumentORM / Base.metadata
        ↓ 提供“期望结构”
Alembic autogenerate
        ↓ 生成候选变更
迁移脚本 upgrade/downgrade
        ↓ 通过 SQLAlchemy Engine
PostgreSQL DDL
```

Alembic 不负责应用数据 CRUD，Repository 也不负责管理表结构。二者分别工作：

```text
Repository → INSERT / SELECT / UPDATE / DELETE
Alembic    → CREATE / ALTER / DROP
```

---

## 16. 迁移不是文件列表，而是有向图

每个 Revision 通过 `down_revision` 指向父版本，因此迁移历史本质上是一张有向无环图。

线性历史：

```text
A → B → C (head)
```

团队中两个人同时从 B 创建迁移，可能形成分支：

```text
      ┌→ C1 (head)
A → B ┤
      └→ C2 (head)
```

此时执行：

```powershell
alembic heads
```

会看到两个 head。普通 `upgrade head` 会因为目标不唯一而产生歧义。

### 16.1 合并分支

```powershell
alembic merge -m "merge migration heads" C1 C2
```

生成合并 Revision：

```text
      ┌→ C1 ┐
A → B ┤     ├→ D (head)
      └→ C2 ┘
```

合并迁移的 `down_revision` 是一个包含两个父版本的元组。它不一定需要执行新的 DDL，主要作用是重新汇合版本图。

### 16.2 不要用改文件名调整顺序

迁移顺序由：

```python
revision
down_revision
```

决定，不由文件名、创建时间或字母顺序决定。

---

## 17. env.py 的实际生命周期

每次运行 Alembic 命令，都会加载 `migrations/env.py`。典型过程：

```text
创建 Alembic Config
→ 读取 alembic.ini
→ 执行 env.py 顶层代码
→ 准备 URL 和 target_metadata
→ 判断 online/offline
→ context.configure(...)
→ context.run_migrations()
```

### 17.1 Online 模式

```powershell
alembic upgrade head
```

`env.py` 创建真实数据库连接，并在连接上执行 DDL。

### 17.2 Offline 模式

```powershell
alembic upgrade head --sql
```

不连接数据库，只生成 SQL 文本，适用于：

- DBA 需要提前审查 SQL。
- 生产环境不允许应用账号直接执行 DDL。
- 迁移由独立发布系统执行。

限制：某些迁移需要读取数据库当前数据或执行结果，离线模式可能无法完整处理。

### 17.3 `context.configure()` 常用参数

| 参数 | 作用 |
| --- | --- |
| `connection` | 在线迁移使用的连接 |
| `url` | 离线迁移使用的数据库 URL |
| `target_metadata` | 自动生成对比的 ORM 元数据 |
| `compare_type=True` | 比较列类型变化 |
| `compare_server_default=True` | 比较服务器默认值，需谨慎验证 |
| `include_schemas=True` | 将非默认 Schema 纳入比较 |
| `include_object` | 自定义哪些对象参与自动生成 |
| `render_as_batch=True` | 批处理表变更，常用于 SQLite |

---

## 18. `op` 对象和常用 Operations API

迁移文件中的：

```python
from alembic import op
```

`op` 是 Alembic Operations 代理，代表当前迁移上下文。

### 18.1 表操作

```python
op.create_table(...)
op.rename_table("old_name", "new_name")
op.drop_table("documents")
```

### 18.2 列操作

```python
op.add_column("documents", sa.Column("description", sa.Text()))

op.alter_column(
    "documents",
    "name",
    existing_type=sa.String(255),
    type_=sa.String(500),
    existing_nullable=False,
)

op.drop_column("documents", "description")
```

修改列时显式写 `existing_type`、`existing_nullable` 和默认值等现状，可以提高跨数据库和降级的可靠性。

### 18.3 索引

```python
op.create_index(
    "ix_documents_created_at",
    "documents",
    ["created_at"],
)

op.drop_index(
    "ix_documents_created_at",
    table_name="documents",
)
```

### 18.4 唯一、检查和外键约束

```python
op.create_unique_constraint(
    "uq_documents_stored_path",
    "documents",
    ["stored_path"],
)

op.create_check_constraint(
    "ck_documents_file_size_non_negative",
    "documents",
    "file_size >= 0",
)

op.create_foreign_key(
    "fk_chunks_document_id_documents",
    "document_chunks",
    "documents",
    ["document_id"],
    ["id"],
    ondelete="CASCADE",
)
```

对应删除操作需要明确约束名，因此稳定的命名约定非常重要。

### 18.5 执行 SQL

```python
op.execute(
    sa.text("UPDATE documents SET status = 'uploaded' WHERE status IS NULL")
)
```

如果 SQL 中包含动态值，应使用绑定参数或 `op.get_bind()`，不要拼接不可信字符串。

### 18.6 获取当前 Connection

```python
connection = op.get_bind()
result = connection.execute(sa.text("SELECT count(*) FROM documents"))
```

这常用于数据回填，但会让迁移依赖在线数据库，无法直接生成完整离线 SQL。

---

## 19. Autogenerate 的工作机制

执行：

```powershell
alembic revision --autogenerate -m "add description"
```

Alembic 会读取两份结构：

```text
真实数据库结构
→ 通过 SQLAlchemy Inspector 反射

期望结构
→ target_metadata，即 Base.metadata
```

然后生成差异候选。

### 19.1 通常能够检测

- 新增或删除表。
- 新增或删除列。
- 可空性变化。
- 基本索引和显式命名的唯一约束变化。
- 启用比较后的部分类型变化。
- 启用比较后的部分 server default 变化。

### 19.2 不能可靠判断或需要人工处理

- 表或列重命名：可能被识别为“删除旧对象 + 新建对象”。
- 复杂类型转换的数据兼容性。
- 数据回填逻辑。
- 应用代码与数据库变更的发布顺序。
- 数据库函数、触发器、视图、部分扩展对象。
- 无名称约束的稳定识别。
- 某些表达式索引或方言特有配置。
- 业务上是否允许删除数据。

因此 autogenerate 的定位是：

```text
迁移草稿生成器，不是无人审查的自动发布工具
```

---

## 20. 安全生成迁移的标准流程

### 20.1 修改 ORM

```python
description: Mapped[str | None] = mapped_column(Text)
```

### 20.2 确认开发库位于 head

```powershell
alembic current
alembic upgrade head
```

如果数据库落后，自动生成可能把“数据库尚未执行的旧迁移”也当成新差异。

### 20.3 生成候选文件

```powershell
alembic revision --autogenerate -m "add document description"
```

### 20.4 人工检查

检查：

```text
revision/down_revision 是否正确
upgrade 是否只包含预期变更
downgrade 是否对称
是否意外 DROP
现有数据能否满足新约束
默认值属于 Python 端还是数据库端
索引创建是否可能长时间锁表
```

### 20.5 在测试库演练

```powershell
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic check
```

### 20.6 提交代码

一次功能提交通常应同时包含：

```text
ORM 修改
迁移文件
相关 Repository/API 修改
测试
文档
```

---

## 21. Schema Migration 与 Data Migration

### 21.1 Schema Migration

修改结构：

```text
创建表
增加列
修改类型
增加索引和约束
```

### 21.2 Data Migration

把已有数据转换为新格式：

```sql
UPDATE documents
SET status = 'uploaded'
WHERE status IS NULL;
```

### 21.3 为什么两者要谨慎组合

大数据量 UPDATE 可能：

- 持有锁很久。
- 产生大量 WAL。
- 造成表膨胀。
- 延长发布窗口。
- 阻塞正常请求。

小表可以在同一迁移完成；大表更适合分批后台回填，再在后续迁移增加约束。

---

## 22. 新增非空列的安全模式

直接执行：

```sql
ALTER TABLE documents
ADD COLUMN category VARCHAR(32) NOT NULL;
```

如果表已有数据且没有默认值，会失败。

更通用的分阶段方法：

### 第一步：添加可空列

```python
op.add_column(
    "documents",
    sa.Column("category", sa.String(32), nullable=True),
)
```

### 第二步：回填数据

```python
op.execute(
    "UPDATE documents SET category = 'general' WHERE category IS NULL"
)
```

大量数据应分批在迁移外回填。

### 第三步：应用代码开始双写或兼容读取

```text
旧代码仍能运行
新代码开始填写 category
```

### 第四步：增加非空约束

```python
op.alter_column(
    "documents",
    "category",
    existing_type=sa.String(32),
    nullable=False,
)
```

这种“扩展—迁移—收缩”模式比一次强制改变更适合在线系统。

---

## 23. Expand/Contract 零停机思路

当旧版和新版应用可能同时运行时，数据库变更必须向前兼容。

### 23.1 Expand

先做兼容性增加：

- 新增可空列。
- 新建表。
- 新增索引。
- 保留旧列。

旧代码通常仍能工作。

### 23.2 Migrate

- 新代码双写旧列和新列。
- 后台回填历史数据。
- 检查新数据完整性。
- 逐步把读取切换到新结构。

### 23.3 Contract

确认没有旧应用实例后：

- 停止写旧列。
- 删除旧列、旧索引或兼容代码。
- 增加最终非空或唯一约束。

不能在旧代码仍依赖某列时先删除该列。

---

## 24. PostgreSQL DDL 的锁与性能影响

PostgreSQL 多数 DDL 支持事务，但不同操作需要不同锁级别。事务安全不等于完全无阻塞。

需要特别评估：

- 删除或修改列。
- 重写大表的类型转换。
- 添加需要扫描全表验证的约束。
- 在大表上普通创建索引。
- 长事务中的多项 DDL。

### 24.1 并发创建索引

PostgreSQL 支持：

```sql
CREATE INDEX CONCURRENTLY ...;
```

它减少对写入的阻塞，但不能运行在普通事务块内。Alembic 中常需要使用 autocommit block，并处理失败后遗留的无效索引。

示意：

```python
with op.get_context().autocommit_block():
    op.create_index(
        "ix_documents_created_at",
        "documents",
        ["created_at"],
        postgresql_concurrently=True,
    )
```

是否需要并发创建取决于表规模和可接受停机时间。当前学习项目数据量小，普通索引迁移更易理解。

### 24.2 锁超时

发布环境可以考虑为迁移设置合理的 `lock_timeout` 和 `statement_timeout`，避免无限等待，但超时后必须能识别迁移未完成并安全重试。

---

## 25. Downgrade 不一定能恢复数据

结构上可写 downgrade，不代表数据可无损恢复。

例如：

```python
def upgrade():
    op.drop_column("documents", "legacy_code")

def downgrade():
    op.add_column("documents", sa.Column("legacy_code", sa.Text()))
```

回退后列重新出现，但旧数据已经丢失。

因此要区分：

```text
结构可逆
≠
数据可逆
```

生产环境常见策略：

- 破坏性变更延迟多个版本再执行。
- 先备份旧数据。
- 使用新 Revision 向前修复，而不是随意 downgrade。
- 明确标注不可逆迁移，并让 downgrade 给出清晰错误。

---

## 26. `stamp` 的作用和风险

```powershell
alembic stamp head
```

`stamp` 只修改 Alembic 版本记录，不执行迁移中的 DDL。

适用场景：

- 接管一个已经手工建好、且确认结构与某 Revision 完全一致的数据库。
- 修复经过严格核验的版本记录。

危险用法：数据库实际没有表，却执行 `stamp head`。Alembic 会认为所有迁移已完成，之后 `upgrade head` 不会创建表。

执行 stamp 前必须先比较真实结构，不能把它当作“快速跳过错误”的命令。

---

## 27. Branch、Tag 和目标版本表达式

常用目标：

```powershell
alembic upgrade head              # 当前唯一 head
alembic upgrade heads             # 所有分支的 head
alembic upgrade 20260813_01        # 指定 Revision
alembic upgrade +1                # 向前一个版本
alembic downgrade -1              # 回退一个版本
alembic downgrade base            # 回到起点
```

查看结构：

```powershell
alembic heads
alembic branches
alembic history --indicate-current
alembic show 20260813_02
alembic show head
```

分支标签 `branch_labels` 可为复杂迁移图提供逻辑名称，但小型线性项目暂时不必使用。

---

## 28. 多 MetaData 和多 Schema

大型系统可能有多个 Declarative Base：

```python
target_metadata = [CoreBase.metadata, AuditBase.metadata]
```

要求表键不能冲突。

管理非默认 Schema：

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    include_schemas=True,
)
```

模型需要声明 Schema：

```python
__table_args__ = {"schema": "knowledge"}
```

还要考虑：

- Alembic 版本表放在哪个 Schema。
- 数据库账号是否有 USAGE/CREATE 权限。
- 自动生成是否误包含系统或第三方 Schema。
- `search_path` 对无前缀对象名的影响。

当前项目只有 `public` Schema，保持单一 metadata 最清晰。

---

## 29. 过滤自动生成对象

如果数据库中存在不由本项目管理的表，可以使用 `include_object`：

```python
def include_object(
    object_,
    name,
    type_,
    reflected,
    compare_to,
):
    if type_ == "table" and name.startswith("external_"):
        return False
    return True
```

再传入：

```python
context.configure(
    ...,
    include_object=include_object,
)
```

过滤规则必须谨慎：错误过滤会让 Alembic 看不到本应管理的变化。

---

## 30. Batch Operations

部分数据库对 ALTER TABLE 支持有限，Alembic 提供批处理模式：

```python
with op.batch_alter_table("documents") as batch_op:
    batch_op.add_column(sa.Column("description", sa.Text()))
```

在 SQLite 等数据库中，它可能通过：

```text
创建临时新表
→ 复制数据
→ 删除旧表
→ 重命名新表
```

PostgreSQL 原生 ALTER TABLE 能力较强，本项目通常直接使用普通 `op.add_column()` 和 `op.alter_column()`。

---

## 31. 迁移测试应检查什么

只确认命令退出码为 0 不够。迁移测试至少可以检查：

```text
从 base 能否升级到 head
目标表和列是否存在
字段类型、nullable、default 是否正确
约束和索引是否存在
downgrade 是否得到预期旧结构
再次 upgrade 是否成功
ORM 与数据库是否无新差异
```

数据迁移还要准备旧版本样例数据：

```text
升级到旧 Revision
→ 插入旧格式数据
→ 升级到 head
→ 验证数据被正确转换
```

本项目的迁移测试使用独立 `_test` 数据库，并在结束后清理，避免污染开发库。

---

## 32. 迁移失败后的排查流程

### 32.1 先停止重复尝试

不要在不清楚当前事务和结构状态时反复执行命令。

### 32.2 查看当前版本

```powershell
alembic current
alembic history --indicate-current
```

数据库中检查：

```sql
SELECT * FROM alembic_version;
```

### 32.3 检查真实结构

```sql
\d documents
```

或使用 SQLAlchemy Inspector。

### 32.4 判断事务是否自动回滚

PostgreSQL 的事务性 DDL 常能整体回滚，但 `CREATE INDEX CONCURRENTLY` 等特殊操作不遵循普通事务块方式，可能遗留需要处理的对象。

### 32.5 选择修复方式

- 修复尚未共享的迁移文件后重试。
- 已共享/已执行的历史通常新增修复 Revision。
- 只有确认真实结构匹配时才使用 `stamp`。
- 数据丢失风险场景先恢复备份或在副本演练。

不要直接手改 `alembic_version` 来“让报错消失”。

---

## 33. CI/CD 和服务器部署顺序

推荐发布流程：

```text
1. CI 创建临时 PostgreSQL
2. alembic upgrade head
3. 运行 Repository/API 测试
4. alembic check
5. 构建应用镜像
6. 备份或确认恢复点
7. 使用迁移账号执行 alembic upgrade head
8. 验证数据库 Revision
9. 发布/重启兼容新结构的应用
10. 运行健康检查和核心接口冒烟测试
```

对于破坏性变更，应采用 Expand/Contract，把迁移与应用发布拆成多个兼容步骤。

### 33.1 谁来执行迁移

常见方式：

- 发布流水线中的独立 migration job。
- Kubernetes Job/init 流程。
- 运维人员审查 SQL 后执行。
- 单机部署脚本在启动应用前执行。

不建议每个 Web Worker 启动时自行迁移，否则多个实例可能并发执行 DDL，并把迁移失败与应用启动耦合。

---

## 34. 常用命令完整速查

| 命令 | 作用 |
| --- | --- |
| `alembic init migrations` | 初始化迁移目录 |
| `alembic current` | 查看数据库当前 Revision |
| `alembic history` | 查看迁移历史 |
| `alembic history --verbose` | 查看详细历史 |
| `alembic history --indicate-current` | 在历史中标记当前版本 |
| `alembic heads` | 查看所有 head |
| `alembic branches` | 查看分支点 |
| `alembic show head` | 查看某个 Revision 信息 |
| `alembic revision -m "message"` | 创建空迁移 |
| `alembic revision --autogenerate -m "message"` | 根据结构差异生成候选迁移 |
| `alembic upgrade head` | 升级到最新版本 |
| `alembic upgrade +1` | 向前一步 |
| `alembic downgrade -1` | 回退一步 |
| `alembic downgrade base` | 回到迁移起点 |
| `alembic upgrade head --sql` | 输出 SQL，不执行 |
| `alembic check` | 检查是否存在未生成差异 |
| `alembic stamp head` | 只标记版本，不执行 DDL |
| `alembic merge heads -m "message"` | 合并多个 head |
| `alembic edit head` | 用配置的编辑器打开迁移文件 |

---

## 35. 常见误区

### 35.1 修改 ORM 后数据库会自动改变

不会。需要创建迁移并执行 `upgrade`。

### 35.2 Autogenerate 生成的文件可以不看

不能。它无法判断重命名、数据兼容和发布顺序等业务意图。

### 35.3 有 downgrade 就一定不会丢数据

错误。重新创建被删除的列不等于恢复列中的历史数据。

### 35.4 `stamp head` 可以修复所有迁移错误

错误。它只修改版本记录，可能制造“版本显示最新但真实表不存在”的严重不一致。

### 35.5 每次应用启动都自动执行迁移最方便

多实例环境可能并发执行，迁移失败也会阻断所有应用启动。更稳妥的是独立迁移步骤。

### 35.6 `create_all()` 等于 Alembic

`create_all()` 适合测试或一次性创建缺失表，不能描述历史、回退、数据迁移和生产发布顺序。

### 35.7 迁移只要本地成功就够了

生产数据量、锁竞争、数据库权限和扩展情况可能不同。必须在接近生产的环境演练并准备恢复方案。

---

## 36. 建议亲自完成的进阶实验

1. 给 `documents` 增加一个可空 `description`，使用 autogenerate 生成迁移并人工检查。
2. 将它分三步改成非空：添加可空列、回填、增加非空约束。
3. 创建两个并行 Revision，用 `alembic heads` 观察多 head，再创建 merge Revision。
4. 使用 `--sql` 输出完整迁移 SQL，并逐条解释锁和数据风险。
5. 在旧 Revision 插入数据，升级后验证数据迁移结果。
6. 故意让 ORM 与数据库不一致，运行 `alembic check` 观察结果，然后用正确迁移修复。

官方延伸阅读：

- [Alembic 官方教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [Operations Reference](https://alembic.sqlalchemy.org/en/latest/ops.html)
- [Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
- [Branches](https://alembic.sqlalchemy.org/en/latest/branches.html)
