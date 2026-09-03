"""Unit tests for page-aware PDF parsing and OCR markers."""

from hashlib import sha256
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import (
    DocumentParsingError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.parsers import PdfDocumentParser, select_parser

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "week04"


def test_two_page_pdf_preserves_page_numbers_text_and_hash() -> None:
    content = (FIXTURE_DIR / "sample_two_page.pdf").read_bytes()

    result = PdfDocumentParser().parse(content, "sample_two_page.pdf")

    assert [page.page_number for page in result.pages] == [1, 2]
    assert "Native PDF page one: parsing keeps page numbers." in result.pages[0].text
    assert "Native PDF page two: chunks retain source metadata." in result.pages[1].text
    assert [page.requires_ocr for page in result.pages] == [False, False]
    assert all(page.source_type == "parser" for page in result.pages)
    assert result.content_hash == sha256(content).hexdigest()
    assert result.parser_name == "pypdf"
    assert result.parser_version


def test_scanned_pdf_page_is_preserved_and_marked_for_ocr() -> None:
    content = (FIXTURE_DIR / "sample_scanned.pdf").read_bytes()

    result = PdfDocumentParser().parse(content, "sample_scanned.pdf")

    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].text == ""
    assert result.pages[0].requires_ocr is True


def test_low_text_threshold_marks_page_for_ocr() -> None:
    content = (FIXTURE_DIR / "sample_two_page.pdf").read_bytes()

    result = PdfDocumentParser(min_text_chars_per_page=1000).parse(content, "sample.pdf")

    assert all(page.requires_ocr for page in result.pages)


def test_corrupt_pdf_is_converted_to_parsing_error() -> None:
    content = (FIXTURE_DIR / "corrupt.pdf").read_bytes()

    with pytest.raises(DocumentParsingError, match="Unable to parse PDF"):
        PdfDocumentParser().parse(content, "corrupt.pdf")


def test_pdf_parser_rejects_extension_mismatch() -> None:
    with pytest.raises(UnsupportedDocumentTypeError, match="does not support"):
        PdfDocumentParser().parse(b"content", "guide.txt")


def test_parser_selector_can_select_pdf_parser() -> None:
    parser = select_parser("REPORT.PDF", [PdfDocumentParser()])

    assert isinstance(parser, PdfDocumentParser)


def test_pdf_parser_rejects_negative_text_threshold() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        PdfDocumentParser(min_text_chars_per_page=-1)
