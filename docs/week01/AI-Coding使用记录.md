# AI Coding 使用记录

## 记录模板

- 任务：
- 使用的提示词：
- AI 给出的方案：
- 采用的部分：
- 人工修改的部分：
- 验证方式：
- 发现的问题：
- 最终结论：

---

## 2026-08-09：Document 数据模型与 create 方法

- 任务：实现第一版 `Document` 数据模型和 `create` 类方法，暂不实现持久化与 CLI 业务功能。
- 使用的提示词：要求 AI 先解释 `dataclass`、类型注解和 `classmethod`，分步骤实现，并运行 pytest、Ruff 和 mypy。
- AI 给出的方案：使用 `@dataclass` 声明八个文档元数据字段；使用 `Document.create` 统一生成 UUID、文件名、扩展名、默认状态和 UTC 创建时间；为这些行为编写独立测试。
- 采用的部分：数据模型、工厂方法、UUID、UTC 时间、`pathlib.Path` 路径解析和三组测试。
- 人工修改的部分：待学习者完成一次小修改后补充，例如调整测试数据或增加一个断言。
- 验证方式：执行 `pytest`、`ruff check .` 和 `mypy`。
- 发现的问题：第一次检查时 pytest 和 mypy 通过，但 Ruff 的 `UP017` 规则建议在 Python 3.11+ 中使用 `datetime.UTC` 代替 `timezone.utc`。已修改模型及测试，并重新执行检查。
- 最终结论：`Document` 类和 `create` 方法满足本阶段要求；4 个测试通过，Ruff 和 mypy 均无问题。尚未实现 JSON 转换、文件校验和持久化。

---

## 2026-08-09：Document 字典转换

- 任务：实现 `Document.to_dict()` 和 `Document.from_dict(...)`，暂不读写 JSON 文件。
- 使用的提示词：要求继续下一小步，实现对象与字典的双向转换。
- AI 给出的方案：使用 `DocumentData` TypedDict 定义字典契约；显式转换全部八个字段；添加输出、恢复和往返测试。
- 采用的部分：TypedDict、实例方法 `to_dict`、类方法 `from_dict` 和三组转换测试。
- 人工修改的部分：待学习者阅读代码后补充。
- 验证方式：执行 `pytest`、`ruff check .` 和 `mypy`。
- 发现的问题：本次实现首次执行即通过全部检查。需要注意 `TypedDict` 只提供静态类型约束，不会在运行时自动校验来自 JSON 的未知数据。
- 最终结论：对象输出、字典恢复和往返转换均已通过测试；当前共 7 个测试通过，Ruff 和 mypy 均无问题。JSON 文件读写和损坏数据处理留给 Repository 阶段。

---

## 2026-08-09：JSON Repository、文件存储与 CLI

- 任务：建立真实文件存储目录，将文档副本和 JSON 元数据持久化，并完成命令行 CRUD。
- 使用的提示词：要求今天继续推进，以便工作日集中学习和准备下周五的进度汇报；同时确认是否需要存储文档数据的文件夹。
- AI 给出的方案：使用 `data/uploads` 保存文件副本，使用自动创建的 `data/documents.json` 保存元数据；Repository 管理 JSON，Service 管理文件，CLI 提供用户入口。
- 采用的部分：配置、业务异常、原子 JSON 写入、文件复制、目录边界保护、add/list/show/delete 命令和分层测试。
- 人工修改的部分：待学习者完成手工 CLI 演示后补充。
- 验证方式：执行 pytest、Ruff、mypy，并使用 `samples/example.txt` 进行真实 CLI 演示。
- 发现的问题：没有出现代码检查错误。设计中明确区分了文件本体与元数据，并增加了删除路径边界保护；当前 JSON 存储仍不支持多进程并发写入。
- 最终结论：18 个测试通过，Ruff 和 mypy 均无问题。真实 CLI 演示成功添加、列出和展示样例文档；源文件与 uploads 副本的 SHA-256 一致，证明文件内容被完整复制。

---

## 2026-08-11：Python 日志配置

- 任务：增加控制台和文件日志，代码注释使用中文，并为日志配置补充自动化测试。
- 使用的提示词：要求先完成日志配置，新增代码注释使用中文。
- AI 给出的方案：在 CLI 统一初始化根 Logger；使用 StreamHandler 和 RotatingFileHandler；Service 记录业务日志，Repository 记录存储日志；使用临时目录测试控制台与文件输出。
- 采用的部分：中文日志格式、按大小轮转、模块 Logger、日志级别划分和日志测试。
- 人工修改的部分：待学习者手工执行 CLI 并查看 `logs/app.log` 后补充。
- 验证方式：运行 pytest、Ruff、mypy，并执行一次真实 CLI 命令检查日志文件。
- 发现的问题：日志配置会修改全局根 Logger，因此测试必须使用临时日志路径，避免污染正式文件；重复配置时使用 `force=True` 替换旧 Handler，避免重复输出。
- 最终结论：20 个测试通过，Ruff 和 mypy 均无问题。使用不存在的样例路径执行真实 CLI，终端和 `logs/app.log` 均产生带时间、级别和模块名的中文 WARNING/ERROR 日志，CLI 正确返回退出码 1。

---

## 2026-08-12：CLI 完整集成测试

- 任务：补齐 add、list、show、delete 和错误退出的 CLI 自动化集成测试，完成第一周代码闭环。
- 使用的提示词：服务器部署等待新虚拟机，先完成本周剩余任务，之后再提前进入第二周。
- AI 给出的方案：使用 pytest 临时目录构造 `Settings`，通过 monkeypatch 让 CLI 使用隔离的数据与日志目录，在同一测试中运行完整文档生命周期。
- 采用的部分：完整 CLI 调用链、中文文件测试、状态码验证、日志验证和数据清理验证。
- 人工修改的部分：待学习者亲自运行测试并阅读一条完整测试流程后补充。
- 验证方式：运行 pytest、Ruff 和 mypy。
- 发现的问题：第一次执行时，重写旧 help 测试后残留了一行缩进错误，pytest 在测试收集阶段通过 `IndentationError` 发现；删除残留代码后重新执行全量检查。
- 最终结论：CLI 集成测试完成；使用项目内临时目录复验后共 24 个测试通过，Ruff 和 mypy 均无问题。第一周代码功能已闭环，Linux 部署实践等待新虚拟机。
