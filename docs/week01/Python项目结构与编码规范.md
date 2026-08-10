# Python 项目结构与编码规范

本文件用于记录第一周对 Python 项目结构、类型注解、异常处理、日志和测试的学习成果。

## 1. Document 数据模型学习记录

### 1.1 dataclass

`dataclass` 适合表示以保存数据为主要职责的类。在 `Document` 类上添加 `@dataclass` 后，Python 会根据声明的字段自动生成 `__init__`、`__repr__` 和 `__eq__` 等方法，从而减少重复代码。

本次代码：

```python
@dataclass
class Document:
    id: str
    name: str
    file_size: int
```

它允许通过关键字参数创建对象，也能直接比较两个对象的字段是否相等。

### 1.2 类型注解

类型注解描述字段和函数参数预期接收的类型，例如：

```python
file_size: int

def create(cls, original_path: str, stored_path: str, file_size: int) -> Self:
    ...
```

类型注解主要用于帮助开发者阅读代码，并让 mypy 等工具提前发现错误。Python 默认不会因为类型注解而在运行时自动拒绝错误类型，因此仍需要输入校验和测试。

### 1.3 classmethod

普通实例方法的第一个参数是 `self`，需要先有对象才能调用。类方法使用 `@classmethod`，第一个参数是 `cls`，可以直接通过类调用：

```python
document = Document.create(...)
```

本项目使用 `create` 作为工厂方法：调用者提供原始路径、存储路径和文件大小；方法负责生成 ID，并补充文件名、扩展名、默认状态和创建时间。

返回类型使用 `Self`，表示该方法返回当前类的实例。

### 1.4 字段设计

| 字段 | 类型 | 来源 |
| --- | --- | --- |
| `id` | `str` | `create` 使用 UUID 自动生成 |
| `name` | `str` | 从原始路径中提取 |
| `original_path` | `str` | 调用者提供 |
| `stored_path` | `str` | 调用者提供 |
| `file_type` | `str` | 从文件扩展名提取并转为小写 |
| `file_size` | `int` | 调用者提供，单位为字节 |
| `status` | `str` | 当前固定为 `uploaded` |
| `created_at` | `str` | 使用 UTC 时间自动生成 |

### 1.5 create 方法执行过程

```text
接收路径和大小
  → 使用 Path 解析原始路径
  → 使用 UUID 生成唯一 ID
  → 提取文件名和扩展名
  → 设置 uploaded 状态
  → 生成带时区的 UTC 时间
  → 返回 Document 对象
```

本阶段只创建内存中的元数据对象，不检查文件是否存在，也不读取、复制或保存文件。这些职责后续由 Service 和 Repository 分别承担。

### 1.6 测试内容

- 调用者提供的路径和大小得到保留。
- 文件名能够从路径中提取。
- 扩展名统一转换为小写。
- 自动生成非空 ID。
- 每个文档的 ID 不相同。
- 默认状态为 `uploaded`。
- 创建时间为带 UTC 时区的 ISO 格式。

## 2. Document 字典转换

### 2.1 为什么需要转换

`Document` 是 Python 对象，而后续 JSON 文件保存的是由字符串、数字、列表和字典组成的数据。因此需要建立两个方向的转换：

```text
Document 对象 --to_dict()--> 字典 --json.dump()--> JSON 文件
Document 对象 <--from_dict()-- 字典 <--json.load()-- JSON 文件
```

本阶段只完成对象与字典之间的转换，尚未调用 `json.dump` 或 `json.load`。

### 2.2 TypedDict

`DocumentData` 是一个 `TypedDict`。它在运行时仍然是普通字典，但能告诉 mypy 字典应该有哪些键，以及每个值的类型。例如 `file_size` 必须是 `int`，其余字段当前为 `str`。

```python
class DocumentData(TypedDict):
    id: str
    file_size: int
```

`TypedDict` 不能代替运行时数据校验。如果 JSON 数据缺少字段、字段类型错误或内容损坏，后续 Repository 仍需要捕获并转换为清晰的存储异常。

### 2.3 to_dict

`to_dict` 是实例方法，因为转换开始时已经有一个 `Document` 对象。它通过 `self` 读取所有字段，返回 `DocumentData`。

采用显式列出字段的写法，可以清楚看到存储结构，也避免未来意外把不应持久化的内部字段写入 JSON。

### 2.4 from_dict

`from_dict` 是类方法，因为转换开始时还没有 `Document` 对象。它通过 `cls(...)` 创建并返回一个新对象。

当前方法假设输入符合 `DocumentData` 契约，不负责自动补字段或转换错误类型。

### 2.5 往返测试

往返测试执行：

```text
原始 Document → to_dict → from_dict → 恢复后的 Document
```

`dataclass` 自动生成的相等比较会逐个比较字段。最终断言两个对象相等，可以证明这次转换没有丢失或修改任何字段。
