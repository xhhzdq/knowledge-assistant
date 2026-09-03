"""Page-aware PDF parser backed by pypdf."""

from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from pypdf import __version__ as pypdf_version
from pypdf.errors import PdfReadError

from knowledge_assistant.exceptions import (
    DocumentParsingError,
    NoExtractableTextError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage
from knowledge_assistant.processing.parsers.base import file_extension


class PdfDocumentParser:
    """Extract native PDF text per page and flag pages that need OCR."""

    parser_name = "pypdf"
    parser_version = pypdf_version
    supported_extensions = frozenset({".pdf"})

    def __init__(self, min_text_chars_per_page: int = 20) -> None:
        if min_text_chars_per_page < 0:
            raise ValueError("min_text_chars_per_page must be non-negative")
        self._min_text_chars_per_page = min_text_chars_per_page

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        extension = file_extension(filename)
        if extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(
                f"{self.parser_name} does not support extension: {extension or '<none>'}"
            )
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise DocumentParsingError(f"Encrypted PDF is not supported: {filename}")
            if not reader.pages:
                raise NoExtractableTextError(f"PDF contains no pages: {filename}")

            pages: list[ParsedPage] = []
            for page_number, page in enumerate(reader.pages, start=1):
                extracted = page.extract_text() or ""
                text = extracted.strip()
                requires_ocr = not text or len(text) < self._min_text_chars_per_page
                pages.append(
                    ParsedPage(
                        page_number=page_number,
                        text=text,
                        source_type="parser",
                        requires_ocr=requires_ocr,
                    )
                )
        except (DocumentParsingError, NoExtractableTextError):
            raise
        except (PdfReadError, OSError, ValueError, TypeError) as exc:
            raise DocumentParsingError(f"Unable to parse PDF: {filename}") from exc

        return ParsedDocument(
            pages=pages,
            content_hash=sha256(content).hexdigest(),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
        )
