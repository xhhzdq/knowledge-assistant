FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖声明，业务代码变化时可以复用依赖安装层缓存。
COPY pyproject.toml README.md ./
COPY src ./src
# 服务器使用 CPU 推理。先从 PyTorch CPU 专用源安装 torch，避免
# sentence-transformers 从普通 PyPI 镜像解析出体积很大的 CUDA 依赖。
# 两个下载地址都只在构建阶段使用，不写入最终容器环境。
RUN python -m pip install --index-url "$PIP_INDEX_URL" --upgrade pip \
    && python -m pip install --index-url "$PYTORCH_INDEX_URL" torch \
    && python -m pip install --index-url "$PIP_INDEX_URL" ".[embedding,ocr]"

# Alembic 在容器中执行迁移时需要这些文件。
COPY alembic.ini ./
COPY migrations ./migrations

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data/uploads /app/logs /models \
    && chown -R app:app /app /models

# 应用进程不需要 root 权限；数据库迁移同样使用该用户执行。
USER app

EXPOSE 8000

CMD ["uvicorn", "knowledge_assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
