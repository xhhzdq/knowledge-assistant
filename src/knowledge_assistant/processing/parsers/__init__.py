"""Document parser interfaces and built-in text parsers."""

from knowledge_assistant.processing.parsers.base import DocumentParser, select_parser
from knowledge_assistant.processing.parsers.docx_parser import DocxDocumentParser
from knowledge_assistant.processing.parsers.pdf_parser import PdfDocumentParser
from knowledge_assistant.processing.parsers.text_parser import (
    MarkdownTextParser,
    Utf8TextParser,
)

__all__ = [
    "DocumentParser",
    "DocxDocumentParser",
    "MarkdownTextParser",
    "PdfDocumentParser",
    "Utf8TextParser",
    "select_parser",
]
