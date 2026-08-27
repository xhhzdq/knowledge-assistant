# 第二周 AI Coding 使用记录

## 2026-08-12：Pydantic Schema 与 API 路由拆分

- 任务：完成阶段 2 的 Pydantic Schema、APIRouter、依赖注入和文档列表接口，并预留一个接口供学习者实现。
- 使用的提示词：要求完成阶段 2，同时保留一个接口让学习者自己编写。
- AI 给出的方案：实现分页列表接口；将详情接口注册为明确的 501 占位；通过 `Depends` 提供 Service；通过 `dependency_overrides` 隔离测试数据。
- 采用的部分：四组 Pydantic Schema、文档 Router、分页参数约束、响应字段过滤、测试依赖覆盖和占位接口。
- 人工修改的部分：学习者已在上一阶段亲自将健康状态从 `ok` 修改为 `running` 并验证 `--reload`；本阶段将亲自实现文档详情接口和对应测试。
- 验证方式：执行 `pytest --basetemp=.pytest-tmp`、`ruff check .` 和 `mypy`。
- 发现的问题：没有出现测试或静态检查错误。设计时避免让未实现详情接口返回虚假数据，选择 HTTP 501 明确表达当前状态。
- 最终结论：列表、分页、参数校验、Schema 过滤和 OpenAPI 注册均已完成；当前 32 个测试通过。详情接口保留为下一项人工练习。

## 2026-08-13：修正文档详情接口

- 任务：修复学习者编写的文档详情接口。
- 学习者实现思路：调用 Document Service 查询文档，未找到时抛出 HTTP 异常，成功时转换为 `DocumentResponse`。
- 发现的问题：通过 `DocumentService` 类调用了实例方法，导致缺少 `self`；同时使用 `if not document` 判断不存在，但 Repository 实际会抛出 `DocumentNotFoundError`。
- 修复方式：改为调用依赖注入得到的 `service.get_document(document_id)`；捕获领域异常并转换为 HTTP 404；补充成功响应、路径过滤和不存在场景测试。
- 验证方式：执行目标 API 测试和全量 pytest、Ruff、mypy。
- 最终结论：目标 API 测试 9 项通过，全量 33 项测试通过，Ruff 和 mypy 均无问题。详情接口现在能返回 200，并在文档不存在时返回 404。
