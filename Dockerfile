FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖声明，业务代码变化时可以复用依赖安装层缓存。
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

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
