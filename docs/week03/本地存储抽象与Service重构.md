# 本地存储抽象与 Service 重构

## 1. 本阶段解决的问题

第二周的 `DocumentService` 直接使用 `Path`、`open()`、`copy2()` 和 `unlink()` 操作本地文件。这种实现可以运行，但业务层知道了过多文件系统细节，后续切换 MinIO 时必须大幅修改 Service。

本阶段引入存储抽象：

```text
CLI / FastAPI
      ↓
DocumentService
      ↓
DocumentStorage Protocol
      ↓
LocalDocumentStorage
```

Service 只表达“保存、判断存在、删除”这些业务需要的能力，不关心底层是 Windows 目录、Linux 目录还是 MinIO Bucket。

## 2. Protocol 的作用

`DocumentStorage` 使用 Python `Protocol` 定义结构化接口：

```python
class DocumentStorage(Protocol):
    def save(self, filename: str, source: BinaryIO) -> StoredObject: ...
    def delete(self, object_key: str) -> None: ...
    def exists(self, object_key: str) -> bool: ...
```

实现类不需要显式继承某个抽象基类；只要方法名称、参数和返回类型兼容，mypy 就可以把它视为 `DocumentStorage`。这称为结构化子类型，也常被称为静态鸭子类型。

它带来的好处：

- Service 不导入 MinIO SDK。
- 单元测试可以使用本地实现或 Fake 实现。
- CLI 和 API 可以组装不同 Adapter。
- 更换存储实现不需要修改 Router 和 Repository。

## 3. StoredObject 为什么必要

存储操作不能只返回路径字符串，因为调用者还需要文件大小，未来可能需要 ETag：

```python
@dataclass(frozen=True)
class StoredObject:
    object_key: str
    file_size: int
    etag: str | None = None
```

本地存储暂时没有 ETag，因此返回 `None`；MinIO 上传完成后可以返回对象的 ETag。Service 依赖的是统一返回结构，不需要根据存储类型分别处理。

## 4. 对象 Key 与本地绝对路径

新的 `stored_path` 过渡期保存相对对象 Key：

```text
documents/8a73...c91.txt
```

不再保存：

```text
D:\Study\knowledge-assistant\data\uploads\8a73..._guide.txt
```

原因是绝对路径只在当前机器有效，而对象 Key 可以同时映射到：

```text
本地：data/uploads/documents/<uuid>.txt
MinIO：Bucket 中的 documents/<uuid>.txt
```

原始文件名仍保存在 Document 的 `name` 字段，随机对象 Key 用于避免重名、路径穿越和文件名兼容问题。

## 5. LocalDocumentStorage 的实现点

### 5.1 唯一对象 Key

本地实现使用 UUID 和小写扩展名生成：

```text
documents/{32位UUID十六进制}.{扩展名}
```

即使两个用户上传同名文件，也不会覆盖。

### 5.2 分块写入与大小限制

文件流按块读取，而不是一次全部加载进内存。累计大小超过上限时抛出 `ValueError`，并在异常处理中删除部分文件。

Service 将大小超限转换为 `InvalidDocumentError`，API 再转换为 HTTP 400。这样存储层、业务层和 HTTP 层各自负责一层语义。

### 5.3 路径边界保护

`_resolve_object_path()` 会把对象 Key 解析成绝对路径，再使用 `relative_to(upload_dir)` 验证最终路径必须位于上传目录内。

以下 Key 会被拒绝：

```text
../outside.txt
documents/../../outside.txt
D:\other\important.txt
```

这项检查必须同时用于 `delete()` 和 `exists()`，否则恶意或损坏的数据库元数据可能删除应用目录外的文件。

### 5.4 幂等删除

删除不存在的对象不会报错。重复调用删除得到相同的最终状态：对象不存在。这种性质称为幂等性。

## 6. Service 的保存一致性

CLI 的 `add_document()` 和 API 的 `add_uploaded_document()` 最终复用 `_store_document()`：

```text
storage.save()
  → 得到 object_key 和 file_size
  → 创建 Document
  → repository.add()
```

如果原文件已经保存，但元数据保存失败，Service 会补偿调用：

```text
storage.delete(object_key)
```

从而减少没有数据库记录的孤儿文件。如果补偿删除本身失败，会记录异常日志，同时保留最初的数据库异常。

## 7. 删除顺序与权衡

当前删除流程为：

```text
查询 Document
  → storage.exists() 做路径安全预检查
  → repository.delete() 删除元数据
  → storage.delete() 删除原文件
```

数据库删除失败时，原文件尚未被删除，因此不会出现“元数据仍在但原文件消失”。如果数据库删除成功而对象删除失败，会留下孤儿对象并记录 warning，后续可以通过清理任务重试。

数据库和对象存储无法使用同一个普通数据库事务做到绝对原子性。实际系统通常使用补偿、重试、状态字段或异步清理任务达到最终一致性。

## 8. 依赖注入

CLI 和 API 当前都组装本地 Adapter：

```text
JsonDocumentRepository + LocalDocumentStorage → CLI
SqlAlchemyDocumentRepository + LocalDocumentStorage → FastAPI
```

接入 MinIO 时，只需要在 API 依赖注入中改为：

```text
SqlAlchemyDocumentRepository + MinioDocumentStorage → FastAPI
```

Service、Router 和 Pydantic Schema 不需要知道 MinIO Client 的存在。

## 9. 测试结果

本阶段新增并覆盖：

- 保存返回对象 Key 和文件大小。
- 文件实际落盘。
- 超限文件不残留。
- 相同文件名生成不同 Key。
- 扩展名规范化。
- 空文件和接近上限文件。
- 幂等删除和存在检查。
- `..` 路径穿越被拒绝。
- Repository 保存失败时清理已保存对象。
- CLI、API 与 PostgreSQL 完整回归。

最终结果：

```text
pytest：70 passed
Ruff：通过
mypy：31 个源码文件通过
```

## 10. 下一步

下一阶段只进行 MinIO 独立环境实验：启动容器、访问 Console、创建 Bucket、手工上传和删除对象。确认基础概念和网络配置后，再实现 `MinioDocumentStorage`，不与 Redis 同时开发。
