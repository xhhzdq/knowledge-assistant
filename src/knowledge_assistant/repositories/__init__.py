"""Persistence adapters for the Knowledge Assistant."""

from knowledge_assistant.repositories.chunk_repository import (
    DocumentChunkRepository,
    SqlAlchemyDocumentChunkRepository,
)

__all__ = ["DocumentChunkRepository", "SqlAlchemyDocumentChunkRepository"]
