"""Traceable, boundary-aware text normalization and chunking."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from knowledge_assistant.processing.models import (
    ChunkSource,
    ParsedDocument,
    TextChunk,
)

TokenCounter = Callable[[str], int]
BoundaryKind = Literal["heading", "paragraph", "sentence", "line", "whitespace"]

_HEADING_START = re.compile(r"(?m)^#{1,6}[ \t]+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_END = re.compile(r"[。！？!?；;](?:[\"'”’」』】）》])?|\.(?:\s|$)")
_LINE_BREAK = re.compile(r"\n")
_WHITESPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class _PageSpan:
    start: int
    end: int
    page_number: int | None
    source_type: Literal["parser", "ocr"]
    ocr_confidence: float | None


@dataclass(frozen=True)
class _NormalizedDocument:
    text: str
    spans: list[_PageSpan]


@dataclass(frozen=True)
class _Region:
    start: int
    end: int


def normalize_text(text: str) -> str:
    """Normalize newlines, trailing spaces, and repeated blank lines."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank:
            if output and not previous_blank:
                output.append("")
        else:
            output.append(line)
        previous_blank = blank
    while output and not output[-1]:
        output.pop()
    return "\n".join(output).strip()


def _normalize_document(document: ParsedDocument) -> _NormalizedDocument:
    parts: list[str] = []
    spans: list[_PageSpan] = []
    cursor = 0
    for page in document.pages:
        text = normalize_text(page.text)
        if not text:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append(
            _PageSpan(
                start=start,
                end=cursor,
                page_number=page.page_number,
                source_type=page.source_type,
                ocr_confidence=page.ocr_confidence,
            )
        )
    return _NormalizedDocument("".join(parts), spans)


def normalize_document_text(document: ParsedDocument) -> str:
    """Return the exact normalized coordinate space used by chunk ranges."""
    return _normalize_document(document).text


def _character_count(text: str) -> int:
    return len(text)


class TextChunker:
    """Split normalized documents at structural boundaries with bounded overlap."""

    def __init__(
        self,
        target_chars: int = 800,
        max_chars: int = 1000,
        overlap_chars: int = 100,
        token_counter: TokenCounter | None = None,
    ) -> None:
        if target_chars <= 0:
            raise ValueError("target_chars must be positive")
        if max_chars < target_chars:
            raise ValueError("max_chars must be greater than or equal to target_chars")
        if overlap_chars < 0 or overlap_chars >= target_chars:
            raise ValueError("overlap_chars must be non-negative and smaller than target_chars")
        self._target_chars = target_chars
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars
        self._token_counter = token_counter or _character_count

    @staticmethod
    def _regions(spans: list[_PageSpan]) -> list[_Region]:
        """Use every OCR page as a hard boundary; parser-only pages may be joined."""
        regions: list[_Region] = []
        parser_start: int | None = None
        parser_end: int | None = None
        for span in spans:
            if span.source_type == "ocr":
                if parser_start is not None and parser_end is not None:
                    regions.append(_Region(parser_start, parser_end))
                    parser_start = None
                    parser_end = None
                regions.append(_Region(span.start, span.end))
            else:
                if parser_start is None:
                    parser_start = span.start
                parser_end = span.end
        if parser_start is not None and parser_end is not None:
            regions.append(_Region(parser_start, parser_end))
        return regions

    @staticmethod
    def _boundary_positions(text: str, region: _Region) -> dict[BoundaryKind, list[int]]:
        section = text[region.start : region.end]

        def absolute(matches: Iterable[re.Match[str]], use_end: bool = False) -> list[int]:
            return [
                region.start + (match.end() if use_end else match.start())
                for match in matches
            ]

        return {
            "heading": absolute(_HEADING_START.finditer(section)),
            "paragraph": absolute(_PARAGRAPH_BREAK.finditer(section)),
            "sentence": absolute(_SENTENCE_END.finditer(section), use_end=True),
            "line": absolute(_LINE_BREAK.finditer(section)),
            "whitespace": absolute(_WHITESPACE.finditer(section)),
        }

    def _choose_end(
        self,
        start: int,
        region_end: int,
        boundaries: dict[BoundaryKind, list[int]],
    ) -> int:
        if region_end - start <= self._max_chars:
            return region_end
        ideal = start + self._target_chars
        hard_end = min(start + self._max_chars, region_end)
        minimum = start + max(1, self._target_chars // 2)
        for kind in ("heading", "paragraph", "sentence", "line", "whitespace"):
            candidates = [
                position
                for position in boundaries[kind]
                if minimum <= position <= hard_end
            ]
            if candidates:
                return min(candidates, key=lambda position: (abs(position - ideal), position))
        return hard_end

    def _next_start(self, text: str, current_start: int, end: int) -> int:
        if self._overlap_chars == 0:
            return end
        next_start = max(current_start + 1, end - self._overlap_chars)
        while next_start < end and text[next_start].isspace():
            next_start += 1
        if (
            0 < next_start < end
            and text[next_start - 1].isascii()
            and text[next_start - 1].isalnum()
            and text[next_start].isascii()
            and text[next_start].isalnum()
        ):
            while next_start < end and text[next_start].isascii() and text[next_start].isalnum():
                next_start += 1
            while next_start < end and text[next_start].isspace():
                next_start += 1
        return next_start

    def _ranges_for_region(self, text: str, region: _Region) -> list[tuple[int, int]]:
        boundaries = self._boundary_positions(text, region)
        ranges: list[tuple[int, int]] = []
        start = region.start
        while start < region.end:
            while start < region.end and text[start].isspace():
                start += 1
            if start >= region.end:
                break
            end = self._choose_end(start, region.end, boundaries)
            while end > start and text[end - 1].isspace():
                end -= 1
            if end <= start:
                end = min(start + self._max_chars, region.end)
            ranges.append((start, end))
            if end >= region.end:
                break
            start = self._next_start(text, start, end)
        return ranges

    @staticmethod
    def _metadata(
        spans: list[_PageSpan], start: int, end: int
    ) -> tuple[int | None, int | None, ChunkSource, float | None]:
        covered = [span for span in spans if span.start < end and span.end > start]
        sources = {span.source_type for span in covered}
        source_type: ChunkSource
        if len(sources) > 1:
            source_type = "mixed"
        elif sources == {"ocr"}:
            source_type = "ocr"
        else:
            source_type = "parser"
        page_numbers = [span.page_number for span in covered if span.page_number is not None]
        page_start = min(page_numbers) if page_numbers else None
        page_end = max(page_numbers) if page_numbers else None
        confidences = [
            span.ocr_confidence
            for span in covered
            if span.source_type == "ocr" and span.ocr_confidence is not None
        ]
        confidence = sum(confidences) / len(confidences) if confidences else None
        return page_start, page_end, source_type, confidence

    def split(
        self,
        document: ParsedDocument,
        document_id: str,
        processing_version: int,
    ) -> list[TextChunk]:
        """Return ordered chunks whose ranges point into ``normalize_document_text``."""
        UUID(document_id)
        if processing_version <= 0:
            raise ValueError("processing_version must be positive")
        normalized = _normalize_document(document)
        if not normalized.text:
            return []

        ranges: list[tuple[int, int]] = []
        for region in self._regions(normalized.spans):
            ranges.extend(self._ranges_for_region(normalized.text, region))

        created_at = datetime.now(UTC)
        chunks: list[TextChunk] = []
        for start, end in ranges:
            content = normalized.text[start:end]
            if not content.strip():
                continue
            page_start, page_end, source_type, confidence = self._metadata(
                normalized.spans, start, end
            )
            token_count = self._token_counter(content)
            if token_count <= 0:
                raise ValueError("token_counter must return a positive value")
            chunks.append(
                TextChunk(
                    id=str(uuid4()),
                    document_id=document_id,
                    processing_version=processing_version,
                    chunk_index=len(chunks),
                    content=content,
                    content_hash=sha256(content.encode("utf-8")).hexdigest(),
                    char_start=start,
                    char_end=end,
                    page_start=page_start,
                    page_end=page_end,
                    source_type=source_type,
                    ocr_confidence=confidence,
                    token_count=token_count,
                    created_at=created_at,
                )
            )
        return chunks
