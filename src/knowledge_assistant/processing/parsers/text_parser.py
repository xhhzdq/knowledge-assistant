"""Strict UTF-8 parsers for plain text and Markdown documents."""

from hashlib import sha256

from knowledge_assistant.exceptions import (
    DocumentParsingError,
    NoExtractableTextError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage
from knowledge_assistant.processing.parsers.base import file_extension


class _Utf8DocumentParser:
    """Shared implementation that preserves decoded source text verbatim."""

    parser_name = "utf8-text"
    parser_version = "1"
    supported_extensions: frozenset[str] = frozenset()

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        extension = file_extension(filename)
        if extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(
                f"{self.parser_name} does not support extension: {extension or '<none>'}"
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParsingError(f"Document is not valid UTF-8: {filename}") from exc

        normalized_text = text.strip()
        if not normalized_text:
            raise NoExtractableTextError(f"Document contains no extractable text: {filename}")

        return ParsedDocument(
            pages=[
                ParsedPage(
                    page_number=None,
                    text=normalized_text,
                    source_type="parser",
                )
            ],
            content_hash=sha256(content).hexdigest(),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
        )


class Utf8TextParser(_Utf8DocumentParser):
    """Parse ``.txt`` files using strict UTF-8 decoding."""

    parser_name = "utf8-text"
    supported_extensions = frozenset({".txt"})


class MarkdownTextParser(_Utf8DocumentParser):
    """Parse Markdown as source text without rendering it to HTML."""

    parser_name = "markdown-text"
    supported_extensions = frozenset({".md"})
