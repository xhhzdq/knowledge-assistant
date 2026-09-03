"""Parser protocol and extension-based parser selection."""

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Protocol

from knowledge_assistant.exceptions import UnsupportedDocumentTypeError
from knowledge_assistant.processing.models import ParsedDocument


def file_extension(filename: str) -> str:
    """Return a normalized extension for either POSIX or Windows-style names."""
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


class DocumentParser(Protocol):
    """Framework-independent interface implemented by every document parser."""

    parser_name: str
    parser_version: str
    supported_extensions: frozenset[str]

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        """Parse raw file bytes into ordered text pages."""
        ...


def select_parser(filename: str, parsers: Iterable[DocumentParser]) -> DocumentParser:
    """Select the first parser supporting the normalized file extension."""
    extension = file_extension(filename)
    for parser in parsers:
        if extension in parser.supported_extensions:
            return parser
    display_extension = extension or "<none>"
    raise UnsupportedDocumentTypeError(
        f"Unsupported document extension: {display_extension}"
    )
