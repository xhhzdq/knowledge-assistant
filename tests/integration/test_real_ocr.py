"""Optional smoke test that loads the real PaddleOCR model."""

from pathlib import Path

import pytest

from knowledge_assistant.processing.ocr import PaddleOcrProvider, apply_pdf_ocr
from knowledge_assistant.processing.parsers import PdfDocumentParser

pytestmark = pytest.mark.integration
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "week04"


def test_real_paddleocr_reads_synthetic_image() -> None:
    pytest.importorskip("paddle")
    pytest.importorskip("paddleocr")
    content = (FIXTURE_DIR / "sample_ocr.png").read_bytes()

    page = PaddleOcrProvider(device="cpu").recognize(content, 1)

    normalized = " ".join(page.text.upper().split())
    assert "OCR" in normalized
    assert "FIXTURE" in normalized
    assert page.ocr_confidence is not None
    assert 0 <= page.ocr_confidence <= 1


def test_real_paddleocr_reads_scanned_pdf_page() -> None:
    pytest.importorskip("paddle")
    pytest.importorskip("paddleocr")
    content = (FIXTURE_DIR / "sample_scanned.pdf").read_bytes()
    parsed = PdfDocumentParser().parse(content, "sample_scanned.pdf")

    result = apply_pdf_ocr(parsed, content, PaddleOcrProvider(device="cpu"))

    normalized = " ".join(result.pages[0].text.upper().split())
    assert "SCANNED" in normalized
    assert "FIXTURE" in normalized
    assert result.pages[0].source_type == "ocr"
    assert result.pages[0].page_number == 1


def test_real_paddleocr_reads_chinese_scan() -> None:
    pytest.importorskip("paddle")
    pytest.importorskip("paddleocr")
    content = (FIXTURE_DIR / "sample_ocr_chinese.png").read_bytes()

    page = PaddleOcrProvider(device="cpu").recognize(content, 1)

    normalized = "".join(page.text.split())
    assert "知识助手" in normalized
    assert "中文扫描样例" in normalized
    assert "2026" in normalized
