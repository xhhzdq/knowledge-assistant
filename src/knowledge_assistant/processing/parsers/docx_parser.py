"""DOCX parser preserving paragraph and table order."""

from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile

from docx import Document as OpenXmlDocument
from docx import __version__ as python_docx_version
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph

from knowledge_assistant.exceptions import (
    DocumentParsingError,
    NoExtractableTextError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage
from knowledge_assistant.processing.parsers.base import file_extension


class DocxDocumentParser:
    """Extract DOCX paragraphs and basic table rows in document order."""

    parser_name = "python-docx"
    parser_version = python_docx_version
    supported_extensions = frozenset({".docx"})

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        extension = file_extension(filename)
        if extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(
                f"{self.parser_name} does not support extension: {extension or '<none>'}"
            )
        try:
            document = OpenXmlDocument(BytesIO(content))
            blocks: list[str] = []
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph):
                    paragraph_text = block.text.strip()
                    if paragraph_text:
                        blocks.append(paragraph_text)
                elif isinstance(block, Table):
                    for row in block.rows:
                        row_text = "\t".join(cell.text.strip() for cell in row.cells).strip()
                        if row_text:
                            blocks.append(row_text)
        except (PackageNotFoundError, BadZipFile, KeyError, OSError, ValueError) as exc:
            raise DocumentParsingError(f"Unable to parse DOCX: {filename}") from exc

        if not blocks:
            raise NoExtractableTextError(f"DOCX contains no extractable text: {filename}")

        return ParsedDocument(
            pages=[
                ParsedPage(
                    page_number=None,
                    text="\n".join(blocks),
                    source_type="parser",
                )
            ],
            content_hash=sha256(content).hexdigest(),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
        )
