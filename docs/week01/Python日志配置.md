# Python 日志配置

## 1. 日志的作用

日志用于记录程序在什么时间、哪个模块、以什么级别执行了什么操作。与临时 `print` 相比，日志可以统一格式、按级别过滤、写入文件并长期保留。

## 2. 当前日志结构

程序在 CLI 启动时调用一次 `configure_logging`，配置两个 Handler：

```text
应用日志
├── StreamHandler：输出到控制台
└── RotatingFileHandler：输出到 logs/app.log
```

业务模块通过下面的方式获取 Logger：

```python
logger = logging.getLogger(__name__)
```

`__name__` 会成为日志中的模块名，例如：

```text
knowledge_assistant.services.document_service
```

## 3. 日志格式

```text
时间 | 级别 | 模块名 | 消息
```

示例：

```text
2026-08-11 20:30:00 | INFO | knowledge_assistant.services.document_service | 文档添加成功: id=... name=example.txt size=143
```

## 4. 日志级别

| 级别 | 当前使用场景 |
| --- | --- |
| DEBUG | 元数据读取数量、CLI 命令开始、内部存储操作 |
| INFO | 文档添加或删除成功 |
| WARNING | 源文件不存在、源路径不是文件 |
| ERROR | JSON 读取或写入失败、越界删除、CLI 命令失败 |

默认级别为 INFO，因此 DEBUG 日志当前不会显示。调试时可以把配置级别改为 `logging.DEBUG`。

## 5. 日志轮转

`RotatingFileHandler` 将单个日志文件限制为约 1 MB，并最多保留 3 个历史文件：

```text
app.log
app.log.1
app.log.2
app.log.3
```

这可以防止学习项目长期运行后日志文件无限增长。

## 6. 敏感信息原则

日志中不能记录密码、Token、数据库口令、完整文档正文或其他敏感信息。当前日志只记录文档 ID、名称、大小和必要路径。

## 7. 测试方法

日志测试使用 pytest 的临时目录，验证：

- 中文 INFO 日志出现在控制台。
- 同一条日志写入 UTF-8 文件。
- 格式包含级别和模块名。
- 重复配置时 Handler 数量保持为 2，不发生重复输出。
