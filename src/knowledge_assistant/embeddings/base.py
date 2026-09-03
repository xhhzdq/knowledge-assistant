"""Embedding provider contract shared by processing and search services."""

from typing import Protocol

EmbeddingVector = list[float]


class EmbeddingProvider(Protocol):
    """Convert document/query text into compatible vectors and count model tokens."""

    model_name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        """Embed non-empty document chunks in input order."""
        ...

    def embed_query(self, query: str) -> EmbeddingVector:
        """Embed one search query in the same vector space as documents."""
        ...

    def count_tokens(self, text: str) -> int:
        """Count tokens using the provider's own tokenizer."""
        ...
