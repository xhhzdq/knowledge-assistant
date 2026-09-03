"""文档入库处理流水线。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Protocol

from knowledge_assistant.cache.base import DocumentCache
from knowledge_assistant.embeddings.base import EmbeddingProvider
from knowledge_assistant.exceptions import (
    DocumentProcessingError,
    KnowledgeAssistantError,
    NoExtractableTextError,
    OcrError,
    ProcessingInProgressError,
    StorageError,
    VectorStoreError,
)
from knowledge_assistant.models import Document
from knowledge_assistant.processing.chunker import TextChunker
from knowledge_assistant.processing.models import ParsedDocument, TextChunk
from knowledge_assistant.processing.ocr.base import (
    OcrProvider,
    apply_pdf_ocr,
    parse_image_with_ocr,
)
from knowledge_assistant.processing.parsers.base import DocumentParser, select_parser
from knowledge_assistant.repositories.chunk_repository import DocumentChunkRepository
from knowledge_assistant.storage.base import DocumentStorage
from knowledge_assistant.vectors.base import VectorRecord, VectorRepository

logger = logging.getLogger(__name__)


class ProcessingDocumentRepository(Protocol):
    """处理流水线需要的文档事务能力。"""

    def get_by_id_for_update(self, document_id: str) -> Document:
        """锁定并读取一条文档记录。"""
        ...

    def get_by_id(self, document_id: str) -> Document:
        """不加锁读取一条文档记录。"""
        ...

    def update(self, document: Document) -> Document:
        """更新文档并提交当前事务。"""
        ...

    def rollback(self) -> None:
        """回滚事务并释放行锁。"""
        ...


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    """处理服务返回给上层的框架无关摘要。"""

    document_id: str
    status: str
    processing_version: int
    chunk_count: int
    vector_count: int
    parser_name: str
    ocr_page_count: int
    embedding_model: str
    duration_ms: int
    processed_at: str
    reused: bool = False


class DocumentProcessingService:
    """协调原文件、解析组件、PostgreSQL、Milvus 与 Redis。"""

    def __init__(
        self,
        document_repository: ProcessingDocumentRepository,
        chunk_repository: DocumentChunkRepository,
        storage: DocumentStorage,
        parsers: Sequence[DocumentParser],
        chunker: TextChunker,
        embedding: EmbeddingProvider,
        vectors: VectorRepository,
        *,
        ocr: OcrProvider | None = None,
        cache: DocumentCache | None = None,
    ) -> None:
        self._documents = document_repository
        self._chunks = chunk_repository
        self._storage = storage
        self._parsers = tuple(parsers)
        self._chunker = chunker
        self._embedding = embedding
        self._vectors = vectors
        self._ocr = ocr
        self._cache = cache

    def process(
        self,
        document_id: str,
        *,
        force: bool = False,
        ocr_mode: str = "auto",
    ) -> DocumentProcessingResult:
        """同步完成一次文档处理；异常时保留原文件并记录失败状态。"""
        started_at = monotonic()
        active_document: Document | None = None
        new_vector_ids: list[str] = []

        try:
            # 行锁覆盖状态判定、内容指纹检查和 processing 写入，避免并发重复处理。
            document = self._documents.get_by_id_for_update(document_id)
            active_document = document
            if document.status == "processing":
                self._documents.rollback()
                raise ProcessingInProgressError(
                    f"Document processing is already in progress: {document_id}"
                )

            content = self._read_source(document)
            content_hash = sha256(content).hexdigest()
            if document.status == "ready" and not force and document.content_hash == content_hash:
                chunk_count = self._chunks.count(document_id)
                if chunk_count > 0:
                    self._documents.rollback()
                    self._invalidate_cache(document_id)
                    return self._result(
                        document,
                        chunk_count=chunk_count,
                        parser_name=self._parser_name(document.name),
                        ocr_page_count=0,
                        duration_ms=self._elapsed_ms(started_at),
                        reused=True,
                    )

            processing_document = replace(
                document,
                status="processing",
                processing_version=document.processing_version + 1,
                content_hash=content_hash,
                processing_error=None,
                updated_at=self._now(),
            )
            active_document = self._documents.update(processing_document)

            parsed = self._parse(content, document.name, ocr_mode)
            chunks = self._chunker.split(
                parsed,
                document_id,
                active_document.processing_version,
            )
            if not chunks:
                raise NoExtractableTextError(f"Document produced no chunks: {document.name}")

            embeddings = self._embedding.embed_documents([chunk.content for chunk in chunks])
            if len(embeddings) != len(chunks):
                raise DocumentProcessingError("Embedding result count does not match chunks")

            old_chunk_count = self._chunks.count(document_id)
            old_chunks = self._chunks.list_page(
                document_id,
                offset=0,
                limit=max(1, old_chunk_count),
            )
            records = [
                VectorRecord(
                    chunk_id=chunk.id,
                    document_id=document_id,
                    processing_version=chunk.processing_version,
                    page_start=chunk.page_start,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]
            new_vector_ids = [record.chunk_id for record in records]
            self._vectors.upsert(records)

            # Chunk 先写入当前事务但不提交，文档 ready 更新负责一次性提交二者。
            self._chunks.replace_for_document(document_id, chunks, commit=False)
            completed_at = self._now()
            ready_document = self._documents.update(
                replace(
                    active_document,
                    status="ready",
                    content_hash=parsed.content_hash,
                    processed_at=completed_at,
                    processing_error=None,
                    updated_at=completed_at,
                )
            )

            # 新版本已成为事实来源后再清理旧向量；清理失败不回滚已成功的新版本。
            old_vector_ids = [chunk.id for chunk in old_chunks]
            if old_vector_ids:
                try:
                    self._vectors.delete_by_chunk_ids(old_vector_ids)
                except VectorStoreError:
                    logger.exception("清理旧版本向量失败: document_id=%s", document_id)

            self._invalidate_cache(document_id)
            return self._result(
                ready_document,
                chunk_count=len(chunks),
                parser_name=parsed.parser_name,
                ocr_page_count=sum(page.source_type == "ocr" for page in parsed.pages),
                duration_ms=self._elapsed_ms(started_at),
            )
        except ProcessingInProgressError:
            raise
        except Exception as exc:
            if new_vector_ids:
                self._compensate_vectors(new_vector_ids, document_id)
            if active_document is not None:
                self._mark_failed(active_document, exc)
            self._invalidate_cache(document_id)
            if isinstance(exc, KnowledgeAssistantError):
                raise
            logger.exception("文档处理发生未分类异常: document_id=%s", document_id)
            raise DocumentProcessingError("Document processing failed") from exc

    def _parse(self, content: bytes, filename: str, ocr_mode: str) -> ParsedDocument:
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if extension in {"png", "jpg", "jpeg"}:
            if self._ocr is None:
                raise OcrError("OCR provider is unavailable for image documents")
            return parse_image_with_ocr(content, filename, self._ocr, mode=ocr_mode)

        parser = select_parser(filename, self._parsers)
        parsed = parser.parse(content, filename)
        if extension != "pdf":
            return parsed
        if self._ocr is None:
            if ocr_mode == "force" or any(page.requires_ocr for page in parsed.pages):
                raise OcrError("OCR provider is unavailable for this PDF")
            return parsed
        return apply_pdf_ocr(parsed, content, self._ocr, mode=ocr_mode)

    def list_chunks(
        self,
        document_id: str,
        *,
        offset: int,
        limit: int,
        page_number: int | None = None,
    ) -> tuple[list[TextChunk], int]:
        """只返回文档当前处理版本的 Chunk；未处理文档返回空列表。"""
        document = self._documents.get_by_id(document_id)
        if document.processing_version == 0:
            return [], 0
        chunks = self._chunks.list_page(
            document_id,
            offset,
            limit,
            processing_version=document.processing_version,
            page_number=page_number,
        )
        total = self._chunks.count(
            document_id,
            processing_version=document.processing_version,
            page_number=page_number,
        )
        return list(chunks), total

    def _parser_name(self, filename: str) -> str:
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if extension in {"png", "jpg", "jpeg"}:
            if self._ocr is None:
                raise OcrError("OCR provider is unavailable for image documents")
            return self._ocr.provider_name
        return select_parser(filename, self._parsers).parser_name

    def _read_source(self, document: Document) -> bytes:
        try:
            return self._storage.read(document.stored_path)
        except StorageError:
            raise
        except OSError as exc:
            raise StorageError(f"Unable to read stored document: {document.id}") from exc

    def _mark_failed(self, document: Document, error: Exception) -> None:
        failed_at = self._now()
        try:
            self._documents.update(
                replace(
                    document,
                    status="failed",
                    processing_error=self._safe_error_summary(error),
                    updated_at=failed_at,
                )
            )
        except KnowledgeAssistantError:
            logger.exception("保存文档失败状态失败: document_id=%s", document.id)

    def _compensate_vectors(self, chunk_ids: list[str], document_id: str) -> None:
        try:
            self._vectors.delete_by_chunk_ids(chunk_ids)
        except Exception:
            logger.exception("补偿删除新向量失败: document_id=%s", document_id)

    def _invalidate_cache(self, document_id: str) -> None:
        if self._cache is None:
            return
        try:
            self._cache.delete(document_id)
        except Exception:
            logger.warning("清理文档缓存失败: document_id=%s", document_id, exc_info=True)

    def _result(
        self,
        document: Document,
        *,
        chunk_count: int,
        parser_name: str,
        ocr_page_count: int,
        duration_ms: int,
        reused: bool = False,
    ) -> DocumentProcessingResult:
        return DocumentProcessingResult(
            document_id=document.id,
            status=document.status,
            processing_version=document.processing_version,
            chunk_count=chunk_count,
            vector_count=chunk_count,
            parser_name=parser_name,
            ocr_page_count=ocr_page_count,
            embedding_model=self._embedding.model_name,
            duration_ms=duration_ms,
            processed_at=document.processed_at or document.updated_at,
            reused=reused,
        )

    @staticmethod
    def _safe_error_summary(error: Exception) -> str:
        summaries = {
            StorageError: "无法读取或保存文档处理数据",
            NoExtractableTextError: "文档中没有可处理的文本",
            OcrError: "OCR 识别失败或服务不可用",
            VectorStoreError: "向量存储暂时不可用",
        }
        for error_type, summary in summaries.items():
            if isinstance(error, error_type):
                return summary
        return "文档处理失败，请查看服务日志"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, round((monotonic() - started_at) * 1000))
