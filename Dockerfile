FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖声明，业务代码变化时可以复用依赖安装层缓存。
COPY pyproject.toml README.md ./
COPY src ./src
# PIP_INDEX_URL 可由 Compose 的 .env 覆盖，解决服务器无法直连 PyPI 的问题。
# 使用 ARG 而非 ENV，避免把构建阶段的镜像地址带入最终运行环境。
RUN python -m pip install --index-url "$PIP_INDEX_URL" --upgrade pip \
    && python -m pip install --index-url "$PIP_INDEX_URL" .

# Alembic 在容器中执行迁移时需要这些文件。
COPY alembic.ini ./
COPY migrations ./migrations

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data/uploads /app/logs \
    && chown -R app:app /app

# 应用进程不需要 root 权限；数据库迁移同样使用该用户执行。
USER app

EXPOSE 8000

CMD ["uvicorn", "knowledge_assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
