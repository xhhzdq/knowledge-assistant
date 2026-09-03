"""Tests for normalized, traceable, boundary-aware text chunking."""

from hashlib import sha256
from uuid import uuid4

import pytest

from knowledge_assistant.processing import (
    ParsedDocument,
    ParsedPage,
    TextChunker,
    normalize_document_text,
    normalize_text,
)

DOCUMENT_ID = str(uuid4())
CONTENT_HASH = "a" * 64


def parsed(*pages: ParsedPage) -> ParsedDocument:
    return ParsedDocument(list(pages), CONTENT_HASH, "test-parser", "1.0")


def test_normalize_text_unifies_newlines_and_blank_lines() -> None:
    source = "  标题  \r\n第一行   \r\n\r\n\r\n  \r第二行\t\t\n\n"

    assert normalize_text(source) == "标题\n第一行\n\n第二行"


def test_blank_document_produces_no_chunks() -> None:
    document = parsed(ParsedPage(None, " \r\n\t\n", "parser"))

    assert TextChunker().split(document, DOCUMENT_ID, 1) == []


def test_short_document_produces_one_traceable_chunk() -> None:
    document = parsed(ParsedPage(None, "第一段。\r\n\r\n第二段。", "parser"))
    chunker = TextChunker(token_counter=lambda text: len(text) + 10)

    chunks = chunker.split(document, DOCUMENT_ID, 2)
    normalized = normalize_document_text(document)

    assert len(chunks) == 1
    assert chunks[0].content == normalized
    assert normalized[chunks[0].char_start : chunks[0].char_end] == chunks[0].content
    assert chunks[0].chunk_index == 0
    assert chunks[0].processing_version == 2
    assert chunks[0].content_hash == sha256(normalized.encode()).hexdigest()
    assert chunks[0].token_count == len(normalized) + 10


def test_paragraph_boundary_is_preferred_before_hard_limit() -> None:
    first = "甲" * 25
    second = "乙" * 25
    third = "丙" * 25
    document = parsed(ParsedPage(1, f"{first}\n\n{second}\n\n{third}", "parser"))

    chunks = TextChunker(target_chars=45, max_chars=55, overlap_chars=0).split(
        document, DOCUMENT_ID, 1
    )

    assert chunks[0].content == f"{first}\n\n{second}"
    assert len(chunks[0].content) <= 55
    assert chunks[1].content == third


def test_chinese_sentence_boundary_is_used_for_long_paragraph() -> None:
    sentence = "这是一个用于测试中文边界的句子。"
    document = parsed(ParsedPage(1, sentence * 5, "parser"))

    chunks = TextChunker(target_chars=35, max_chars=45, overlap_chars=0).split(
        document, DOCUMENT_ID, 1
    )

    assert len(chunks) > 1
    assert all(chunk.content.endswith("。") for chunk in chunks)
    assert all(len(chunk.content) <= 45 for chunk in chunks)


def test_hard_split_enforces_maximum_when_no_boundary_exists() -> None:
    document = parsed(ParsedPage(1, "甲" * 121, "parser"))

    chunks = TextChunker(target_chars=40, max_chars=50, overlap_chars=0).split(
        document, DOCUMENT_ID, 1
    )

    assert [len(chunk.content) for chunk in chunks] == [50, 50, 21]


def test_overlap_is_traceable_and_approximately_configured() -> None:
    document = parsed(ParsedPage(1, "甲" * 130, "parser"))
    chunks = TextChunker(target_chars=40, max_chars=50, overlap_chars=10).split(
        document, DOCUMENT_ID, 1
    )
    normalized = normalize_document_text(document)

    assert len(chunks) > 2
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert previous.char_end - current.char_start == 10
        assert previous.content[-10:] == current.content[:10]
    for chunk in chunks:
        assert normalized[chunk.char_start : chunk.char_end] == chunk.content


def test_parser_pages_can_share_chunk_and_keep_page_range() -> None:
    document = parsed(
        ParsedPage(1, "第一页正文。", "parser"),
        ParsedPage(2, "第二页正文。", "parser"),
    )

    chunk = TextChunker(target_chars=100, max_chars=120, overlap_chars=10).split(
        document, DOCUMENT_ID, 1
    )[0]

    assert chunk.page_start == 1
    assert chunk.page_end == 2
    assert chunk.source_type == "parser"
    assert "\n\n" in chunk.content


def test_ocr_page_is_never_merged_with_neighboring_pages() -> None:
    document = parsed(
        ParsedPage(1, "甲" * 20, "parser"),
        ParsedPage(2, "乙" * 20, "ocr", 0.86),
        ParsedPage(3, "丙" * 20, "parser"),
    )

    chunks = TextChunker(target_chars=100, max_chars=120, overlap_chars=10).split(
        document, DOCUMENT_ID, 1
    )

    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]
    assert [chunk.source_type for chunk in chunks] == ["parser", "ocr", "parser"]
    assert chunks[1].ocr_confidence == pytest.approx(0.86)


def test_chunk_indexes_and_ranges_are_stable_across_runs() -> None:
    document = parsed(ParsedPage(1, "知识助手。" * 40, "parser"))
    chunker = TextChunker(target_chars=45, max_chars=55, overlap_chars=8)

    first = chunker.split(document, DOCUMENT_ID, 1)
    second = chunker.split(document, DOCUMENT_ID, 1)

    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert [(chunk.char_start, chunk.char_end) for chunk in first] == [
        (chunk.char_start, chunk.char_end) for chunk in second
    ]
    assert [chunk.content_hash for chunk in first] == [
        chunk.content_hash for chunk in second
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_chars": 0},
        {"target_chars": 100, "max_chars": 99},
        {"target_chars": 100, "overlap_chars": -1},
        {"target_chars": 100, "overlap_chars": 100},
    ],
)
def test_invalid_chunk_windows_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TextChunker(**kwargs)


def test_invalid_identity_version_and_token_count_are_rejected() -> None:
    document = parsed(ParsedPage(1, "正文", "parser"))
    with pytest.raises(ValueError):
        TextChunker().split(document, "not-a-uuid", 1)
    with pytest.raises(ValueError, match="processing_version"):
        TextChunker().split(document, DOCUMENT_ID, 0)
    with pytest.raises(ValueError, match="token_counter"):
        TextChunker(token_counter=lambda _text: 0).split(document, DOCUMENT_ID, 1)
