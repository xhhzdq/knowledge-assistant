"""Embedding contracts and local model providers."""

from knowledge_assistant.embeddings.base import EmbeddingProvider, EmbeddingVector
from knowledge_assistant.embeddings.bge import BgeEmbeddingProvider

__all__ = ["BgeEmbeddingProvider", "EmbeddingProvider", "EmbeddingVector"]
