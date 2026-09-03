"""OCR abstractions and framework-independent orchestration rules."""

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal, Protocol

from knowledge_assistant.exceptions import (
    NoExtractableTextError,
    OcrError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage

OcrMode = Literal["auto", "never", "force"]
PdfPageRenderer = Callable[[bytes, set[int]], Mapping[int, bytes]]


class OcrProvider(Protocol):
    """Recognize one already-rendered page image without persistence side effects."""

    @property
    def provider_name(self) -> str:
        """返回 OCR Provider 名称。"""
        ...

    @property
    def provider_version(self) -> str:
        """返回 OCR Provider 版本。"""
        ...

    def recognize(self, page_image: bytes, page_number: int | None) -> ParsedPage:
        """Return OCR text and confidence for one image."""
        ...


def _validate_mode(mode: str) -> OcrMode:
    if mode not in {"auto", "never", "force"}:
        raise ValueError("OCR mode must be auto, never, or force")
    return mode  # type: ignore[return-value]


def _target_page_numbers(document: ParsedDocument, mode: OcrMode) -> set[int]:
    targets: set[int] = set()
    for page in document.pages:
        if page.page_number is None:
            raise OcrError("PDF OCR requires a physical page number")
        if mode == "force" or page.requires_ocr:
            targets.add(page.page_number)
    return targets


def apply_pdf_ocr(
    document: ParsedDocument,
    pdf_content: bytes,
    provider: OcrProvider,
    renderer: PdfPageRenderer | None = None,
    mode: str = "auto",
) -> ParsedDocument:
    """Replace selected PDF pages with OCR output while preserving page order."""
    selected_mode = _validate_mode(mode)
    targets = _target_page_numbers(document, selected_mode)
    if selected_mode == "never":
        if targets:
            raise OcrError(
                "OCR is disabled but the PDF contains pages that require recognition"
            )
        return document
    if not targets:
        return document

    if renderer is None:
        from knowledge_assistant.processing.ocr.pdf_renderer import render_pdf_pages

        renderer = render_pdf_pages
    try:
        rendered_pages = renderer(pdf_content, targets)
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError("Unable to render PDF pages for OCR") from exc

    replacements: dict[int, ParsedPage] = {}
    for page_number in sorted(targets):
        page_image = rendered_pages.get(page_number)
        if page_image is None:
            raise OcrError(f"PDF renderer did not return page {page_number}")
        recognized = provider.recognize(page_image, page_number)
        if recognized.page_number != page_number:
            raise OcrError(f"OCR provider returned an unexpected page number: {page_number}")
        if recognized.source_type != "ocr":
            raise OcrError("OCR provider must return source_type='ocr'")
        replacements[page_number] = recognized

    pages = [
        replacements.get(page.page_number, page)
        if page.page_number is not None
        else page
        for page in document.pages
    ]
    return ParsedDocument(
        pages=pages,
        content_hash=document.content_hash,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
    )


def parse_image_with_ocr(
    content: bytes,
    filename: str,
    provider: OcrProvider,
    mode: str = "auto",
) -> ParsedDocument:
    """Recognize PNG/JPEG bytes as a one-page parsed document."""
    selected_mode = _validate_mode(mode)
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        raise UnsupportedDocumentTypeError(
            f"OCR image parser does not support extension: {extension or '<none>'}"
        )
    if selected_mode == "never":
        raise OcrError("OCR is disabled for image documents")

    page = provider.recognize(content, 1)
    if page.page_number != 1 or page.source_type != "ocr":
        raise OcrError("OCR provider returned invalid image-page metadata")
    return ParsedDocument(
        pages=[page],
        content_hash=sha256(content).hexdigest(),
        parser_name=provider.provider_name,
        parser_version=provider.provider_version,
    )


def require_recognized_text(texts: list[str], filename: str) -> str:
    """Normalize recognized lines and reject an OCR result with no usable text."""
    text = "\n".join(line.strip() for line in texts if line.strip()).strip()
    if not text:
        raise NoExtractableTextError(f"OCR found no extractable text: {filename}")
    return text
