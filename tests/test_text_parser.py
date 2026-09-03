"""Unit tests for extension selection and UTF-8 text parsers."""

from hashlib import sha256
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import (
    DocumentParsingError,
    NoExtractableTextError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.parsers import (
    MarkdownTextParser,
    Utf8TextParser,
    select_parser,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "week04"


def test_txt_fixture_is_decoded_with_expected_order_and_metadata() -> None:
    content = (FIXTURE_DIR / "sample_utf8.txt").read_bytes()

    result = Utf8TextParser().parse(content, "sample_utf8.txt")

    assert len(result.pages) == 1
    assert result.pages[0].page_number is None
    assert result.pages[0].source_type == "parser"
    assert result.pages[0].text == (
        "Week four text fixture. Parser should preserve this sentence.\n\n"
        "The second paragraph verifies that paragraph boundaries remain observable."
    )
    assert result.content_hash == sha256(content).hexdigest()
    assert result.parser_name == "utf8-text"
    assert result.parser_version == "1"


def test_markdown_fixture_preserves_heading_list_and_body_source() -> None:
    content = (FIXTURE_DIR / "sample_markdown.md").read_bytes()

    result = MarkdownTextParser().parse(content, "sample_markdown.md")

    assert result.pages[0].text == (
        "# Retrieval Fixture\n\n"
        "Semantic retrieval starts with reliable parsing.\n\n"
        "- Preserve headings.\n"
        "- Preserve list item order.\n"
        "- Keep source metadata traceable."
    )
    assert "<h1>" not in result.pages[0].text
    assert result.parser_name == "markdown-text"


@pytest.mark.parametrize(
    ("filename", "expected_type"),
    [
        ("notes.TXT", Utf8TextParser),
        ("D:\\documents\\guide.MD", MarkdownTextParser),
    ],
)
def test_select_parser_uses_case_insensitive_extension(filename: str, expected_type: type) -> None:
    parser = select_parser(filename, [MarkdownTextParser(), Utf8TextParser()])

    assert isinstance(parser, expected_type)


@pytest.mark.parametrize("filename", ["guide.pdf", "README", "archive.tar.gz"])
def test_select_parser_rejects_unsupported_extension(filename: str) -> None:
    with pytest.raises(UnsupportedDocumentTypeError, match="Unsupported document extension"):
        select_parser(filename, [Utf8TextParser(), MarkdownTextParser()])


@pytest.mark.parametrize(
    ("parser", "filename"),
    [
        (Utf8TextParser(), "guide.md"),
        (MarkdownTextParser(), "guide.txt"),
    ],
)
def test_parser_rejects_extension_mismatch(parser: object, filename: str) -> None:
    with pytest.raises(UnsupportedDocumentTypeError, match="does not support"):
        parser.parse(b"valid text", filename)  # type: ignore[attr-defined]


def test_invalid_utf8_is_converted_to_parsing_error() -> None:
    with pytest.raises(DocumentParsingError, match="not valid UTF-8"):
        Utf8TextParser().parse(b"valid prefix\xff", "guide.txt")


@pytest.mark.parametrize("content", [b"", b"  \r\n\t  "])
def test_empty_or_whitespace_only_text_is_rejected(content: bytes) -> None:
    with pytest.raises(NoExtractableTextError, match="no extractable text"):
        Utf8TextParser().parse(content, "empty.txt")


def test_task_zero_empty_fixture_is_rejected() -> None:
    content = (FIXTURE_DIR / "empty.txt").read_bytes()

    with pytest.raises(NoExtractableTextError):
        Utf8TextParser().parse(content, "empty.txt")
