# Knowledge Assistant

企业文档智能问答系统学习项目。本周先完成 Python 工程骨架和命令行文档管理工具，后续逐步接入 FastAPI、数据库、向量检索、Agent 与 MCP。

## 环境要求

- Python 3.11 或更高版本
- Git

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
pytest
ruff check .
mypy
```

## 命令行使用

```powershell
knowledge-assistant add .\samples\example.txt
knowledge-assistant list
knowledge-assistant show <document-id>
knowledge-assistant delete <document-id>
```

`add` 会将文件副本保存到 `data/uploads`，并将元数据保存到首次运行时自动创建的 `data/documents.json`。

## 当前目录结构

```text
knowledge-assistant/
├── src/knowledge_assistant/  # 应用源码
├── tests/                    # 自动化测试
├── data/uploads/             # 本地文档副本（不提交到 Git）
├── docs/week01/              # 第一周学习文档
├── pyproject.toml            # 项目与工具配置
└── README.md
```

## 当前状态

已完成本地文档的添加、列表、详情和删除，以及 JSON 元数据持久化。当前只保存文件及元数据，不解析 PDF 正文，也不进行 OCR。
