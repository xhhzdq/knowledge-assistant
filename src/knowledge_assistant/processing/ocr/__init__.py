"""OCR provider contracts, orchestration helpers, and implementations."""

from knowledge_assistant.processing.ocr.base import (
    OcrMode,
    OcrProvider,
    PdfPageRenderer,
    apply_pdf_ocr,
    parse_image_with_ocr,
)
from knowledge_assistant.processing.ocr.paddle_ocr import PaddleOcrProvider
from knowledge_assistant.processing.ocr.pdf_renderer import render_pdf_pages

__all__ = [
    "OcrMode",
    "OcrProvider",
    "PaddleOcrProvider",
    "PdfPageRenderer",
    "apply_pdf_ocr",
    "parse_image_with_ocr",
    "render_pdf_pages",
]
