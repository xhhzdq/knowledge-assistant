"""Real local BGE smoke tests; never download a model during pytest."""

import math
import os
from pathlib import Path

import pytest

from knowledge_assistant.embeddings import BgeEmbeddingProvider

pytestmark = pytest.mark.integration


def local_model_path() -> Path:
    configured = os.getenv("EMBEDDING_MODEL_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[2]
    return project_root.parent / "models" / "bge-small-zh-v1.5"


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(value * value for value in left))
        * math.sqrt(sum(value * value for value in right))
    )


def test_real_bge_outputs_normalized_512_dimension_vectors() -> None:
    pytest.importorskip("sentence_transformers")
    model_path = local_model_path()
    if not model_path.is_dir():
        pytest.skip(f"local BGE model is absent: {model_path}")
    provider = BgeEmbeddingProvider(model_path, device="cpu")

    vectors = provider.embed_documents(["数据库迁移", "文档向量检索"])

    assert len(vectors) == 2
    assert all(len(vector) == 512 for vector in vectors)
    assert all(math.isclose(cosine(vector, vector), 1.0, abs_tol=1e-5) for vector in vectors)
    assert provider.count_tokens("数据库迁移") > 0


def test_real_bge_ranks_related_document_above_unrelated_document() -> None:
    pytest.importorskip("sentence_transformers")
    model_path = local_model_path()
    if not model_path.is_dir():
        pytest.skip(f"local BGE model is absent: {model_path}")
    provider = BgeEmbeddingProvider(model_path, device="cpu")
    query = provider.embed_query("数据库迁移应该如何执行？")
    related, unrelated = provider.embed_documents(
        [
            "使用 Alembic upgrade head 命令可以把数据库迁移到最新版本。",
            "今天午餐可以选择水果、面包和一杯牛奶。",
        ]
    )

    related_score = cosine(query, related)
    unrelated_score = cosine(query, unrelated)
    assert related_score > unrelated_score + 0.1
