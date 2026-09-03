"""Unit tests for BGE embedding validation and lazy model reuse."""

import math
from pathlib import Path

import pytest

from knowledge_assistant.embeddings import BgeEmbeddingProvider
from knowledge_assistant.exceptions import EmbeddingError

DIMENSION = 4


def unit_vector(index: int = 0, dimension: int = DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    vector[index] = 1.0
    return vector


class FakeEmbeddingModel:
    def __init__(
        self,
        *,
        vectors: list[list[float]] | None = None,
        dimension: int | None = DIMENSION,
        error: Exception | None = None,
    ) -> None:
        self.vectors = vectors
        self.dimension = dimension
        self.error = error
        self.encode_calls: list[tuple[list[str], dict[str, object]]] = []
        self.tokenize_calls: list[list[str]] = []

    def get_embedding_dimension(self) -> int | None:
        return self.dimension

    def encode(self, inputs: list[str], **kwargs: object) -> list[list[float]]:
        self.encode_calls.append((inputs, kwargs))
        if self.error is not None:
            raise self.error
        if self.vectors is not None:
            return self.vectors
        return [unit_vector(index % DIMENSION) for index, _text in enumerate(inputs)]

    def tokenize(self, texts: list[str], **_kwargs: object) -> dict[str, object]:
        self.tokenize_calls.append(texts)
        return {"attention_mask": [[1, 1, 1, 0]]}


def provider_for(model: FakeEmbeddingModel) -> BgeEmbeddingProvider:
    return BgeEmbeddingProvider(
        Path("unused-in-fake-tests"),
        dimension=DIMENSION,
        batch_size=2,
        model_factory=lambda *_args, **_kwargs: model,
    )


def test_empty_document_batch_does_not_load_model() -> None:
    loads = 0

    def factory(*_args: object, **_kwargs: object) -> FakeEmbeddingModel:
        nonlocal loads
        loads += 1
        return FakeEmbeddingModel()

    provider = BgeEmbeddingProvider(
        "unused",
        dimension=DIMENSION,
        model_factory=factory,
    )

    assert provider.embed_documents([]) == []
    assert loads == 0


def test_document_batch_is_normalized_and_preserves_order() -> None:
    model = FakeEmbeddingModel()
    provider = provider_for(model)

    vectors = provider.embed_documents(["第一段", "第二段"])

    assert vectors == [unit_vector(0), unit_vector(1)]
    inputs, kwargs = model.encode_calls[0]
    assert inputs == ["第一段", "第二段"]
    assert kwargs["batch_size"] == 2
    assert kwargs["normalize_embeddings"] is True
    assert kwargs["convert_to_numpy"] is True


def test_query_adds_instruction_but_document_does_not() -> None:
    model = FakeEmbeddingModel()
    provider = provider_for(model)

    provider.embed_documents(["数据库迁移正文"])
    provider.embed_query("  如何执行迁移？  ")

    document_input = model.encode_calls[0][0][0]
    query_input = model.encode_calls[1][0][0]
    assert document_input == "数据库迁移正文"
    assert query_input == "为这个句子生成表示以用于检索相关文章：如何执行迁移？"


def test_model_is_loaded_once_for_embedding_and_token_count() -> None:
    model = FakeEmbeddingModel()
    loads = 0

    def factory(*_args: object, **_kwargs: object) -> FakeEmbeddingModel:
        nonlocal loads
        loads += 1
        return model

    provider = BgeEmbeddingProvider(
        "unused",
        dimension=DIMENSION,
        model_factory=factory,
    )

    provider.embed_documents(["文档"])
    provider.embed_query("问题")
    assert provider.count_tokens("文档内容") == 3
    assert loads == 1


def test_token_count_uses_attention_mask() -> None:
    model = FakeEmbeddingModel()

    assert provider_for(model).count_tokens("三个 token") == 3
    assert model.tokenize_calls == [["三个 token"]]


@pytest.mark.parametrize("value", ["", " ", "\r\n"])
def test_blank_documents_queries_and_token_inputs_are_rejected(value: str) -> None:
    provider = provider_for(FakeEmbeddingModel())
    with pytest.raises(ValueError, match="blank"):
        provider.embed_documents([value])
    with pytest.raises(ValueError, match="blank"):
        provider.embed_query(value)
    with pytest.raises(ValueError, match="blank"):
        provider.count_tokens(value)


def test_model_dimension_is_checked_when_loaded() -> None:
    provider = provider_for(FakeEmbeddingModel(dimension=8))

    with pytest.raises(EmbeddingError, match="configured 4, model 8"):
        provider.embed_documents(["正文"])


def test_vector_count_and_dimension_are_checked() -> None:
    wrong_count = provider_for(FakeEmbeddingModel(vectors=[unit_vector()]))
    wrong_dimension = provider_for(FakeEmbeddingModel(vectors=[[1.0, 0.0]]))

    with pytest.raises(EmbeddingError, match="count mismatch"):
        wrong_count.embed_documents(["一", "二"])
    with pytest.raises(EmbeddingError, match="expected 4, received 2"):
        wrong_dimension.embed_documents(["正文"])


def test_non_finite_and_unnormalized_vectors_are_rejected() -> None:
    non_finite = provider_for(
        FakeEmbeddingModel(vectors=[[math.nan, 0.0, 0.0, 1.0]])
    )
    unnormalized = provider_for(FakeEmbeddingModel(vectors=[[1.0, 1.0, 0.0, 0.0]]))

    with pytest.raises(EmbeddingError, match="non-finite"):
        non_finite.embed_documents(["正文"])
    with pytest.raises(EmbeddingError, match="not normalized"):
        unnormalized.embed_documents(["正文"])


def test_inference_failure_is_converted_to_embedding_error() -> None:
    provider = provider_for(FakeEmbeddingModel(error=RuntimeError("boom")))

    with pytest.raises(EmbeddingError, match="inference failed"):
        provider.embed_documents(["正文"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_path": ""},
        {"model_path": "unused", "dimension": 0},
        {"model_path": "unused", "batch_size": 0},
        {"model_path": "unused", "device": "tpu"},
        {"model_path": "unused", "query_instruction": " "},
    ],
)
def test_invalid_provider_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        BgeEmbeddingProvider(**kwargs)
