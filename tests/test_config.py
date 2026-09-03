"""Tests for fourth-week processing configuration."""

import pytest
from pydantic import ValidationError

from knowledge_assistant.core.config import (
    EmbeddingSettings,
    MilvusSettings,
    OcrSettings,
    ProcessingSettings,
)


def test_fourth_week_settings_accept_valid_configuration() -> None:
    processing = ProcessingSettings(
        chunk_target_chars=800,
        chunk_max_chars=1000,
        chunk_overlap_chars=100,
    )
    ocr = OcrSettings(
        ocr_enabled=True,
        ocr_provider="paddle",
        ocr_device="cpu",
        ocr_min_text_chars_per_page=20,
    )
    embedding = EmbeddingSettings(
        embedding_provider="bge",
        embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_model_path="/models/bge-small-zh-v1.5",
        embedding_dimension=512,
        embedding_batch_size=16,
        embedding_device="cpu",
    )
    milvus = MilvusSettings(
        milvus_uri="http://milvus:19530",
        milvus_collection="document_chunks_v1",
        milvus_metric_type="COSINE",
        milvus_timeout_seconds=5,
    )

    assert processing.chunk_overlap_chars == 100
    assert ocr.ocr_min_text_chars_per_page == 20
    assert embedding.embedding_dimension == 512
    assert milvus.milvus_collection == "document_chunks_v1"


@pytest.mark.parametrize(
    ("target", "maximum", "overlap"),
    [
        (1001, 1000, 100),
        (800, 1000, 800),
        (800, 1000, 801),
    ],
)
def test_processing_settings_reject_invalid_chunk_window(
    target: int,
    maximum: int,
    overlap: int,
) -> None:
    with pytest.raises(ValidationError):
        ProcessingSettings(
            chunk_target_chars=target,
            chunk_max_chars=maximum,
            chunk_overlap_chars=overlap,
        )


@pytest.mark.parametrize("dimension", [0, -1, 65_536])
def test_embedding_settings_reject_invalid_dimension(dimension: int) -> None:
    with pytest.raises(ValidationError):
        EmbeddingSettings(embedding_dimension=dimension)


@pytest.mark.parametrize("batch_size", [0, -1, 1025])
def test_embedding_settings_reject_invalid_batch_size(batch_size: int) -> None:
    with pytest.raises(ValidationError):
        EmbeddingSettings(embedding_batch_size=batch_size)


@pytest.mark.parametrize("uri", ["", "milvus:19530", "not-a-url"])
def test_milvus_settings_reject_empty_or_invalid_uri(uri: str) -> None:
    with pytest.raises(ValidationError):
        MilvusSettings(milvus_uri=uri)


@pytest.mark.parametrize("collection", ["", "123_chunks", "document-chunks", "chunks/v1"])
def test_milvus_settings_reject_invalid_collection_name(collection: str) -> None:
    with pytest.raises(ValidationError):
        MilvusSettings(milvus_collection=collection)


@pytest.mark.parametrize("timeout", [0, -1, 301])
def test_milvus_settings_reject_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValidationError):
        MilvusSettings(milvus_timeout_seconds=timeout)
