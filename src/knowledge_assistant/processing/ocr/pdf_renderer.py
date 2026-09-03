"""Render selected PDF pages into PNG bytes for OCR."""

import importlib
from io import BytesIO
from typing import Any

from knowledge_assistant.exceptions import OcrError


def render_pdf_pages(pdf_content: bytes, page_numbers: set[int]) -> dict[int, bytes]:
    """Render only requested one-based pages using the optional pypdfium2 runtime."""
    if not pdf_content:
        raise OcrError("PDF bytes must not be empty")
    if any(page_number <= 0 for page_number in page_numbers):
        raise OcrError("PDF page numbers must be positive")
    if not page_numbers:
        return {}
    try:
        pdfium: Any = importlib.import_module("pypdfium2")
    except ImportError as exc:
        raise OcrError(
            "PDF OCR rendering requires the project's 'ocr' optional dependencies"
        ) from exc

    document: Any | None = None
    try:
        document = pdfium.PdfDocument(pdf_content)
        page_count = len(document)
        missing = sorted(number for number in page_numbers if number > page_count)
        if missing:
            raise OcrError(f"PDF does not contain requested page {missing[0]}")

        rendered: dict[int, bytes] = {}
        for page_number in sorted(page_numbers):
            page = document[page_number - 1]
            try:
                bitmap = page.render(scale=2.0)
                try:
                    image = bitmap.to_pil()
                    output = BytesIO()
                    image.save(output, format="PNG")
                    rendered[page_number] = output.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()
        return rendered
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError("Unable to render PDF pages for OCR") from exc
    finally:
        if document is not None:
            document.close()
