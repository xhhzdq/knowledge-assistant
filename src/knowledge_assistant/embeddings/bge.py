"""Local sentence-transformers adapter for BGE Chinese embeddings."""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from threading import Lock
from typing import ClassVar, Protocol, cast

from knowledge_assistant.embeddings.base import EmbeddingVector
from knowledge_assistant.exceptions import EmbeddingError


class SentenceTransformerModel(Protocol):
    """Subset of SentenceTransformer used by this provider."""

    def encode(self, inputs: list[str], **kwargs: object) -> object:
        """Encode a batch of text."""
        ...

    def tokenize(self, texts: list[str], **kwargs: object) -> Mapping[str, object]:
        """Tokenize a batch of text."""
        ...

    def get_embedding_dimension(self) -> int | None:
        """Return the model output dimension when known."""
        ...


ModelFactory = Callable[..., SentenceTransformerModel]


class BgeEmbeddingProvider:
    """Generate normalized BGE vectors from an explicitly local model directory."""

    DEFAULT_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
    _models: ClassVar[dict[tuple[str, str], SentenceTransformerModel]] = {}
    _model_lock: ClassVar[Lock] = Lock()

    def __init__(
        self,
        model_path: str | Path,
        *,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        dimension: int = 512,
        batch_size: int = 16,
        device: str = "cpu",
        query_instruction: str = DEFAULT_QUERY_INSTRUCTION,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if not str(model_path).strip():
            raise ValueError("model_path must not be blank")
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if device not in {"cpu", "gpu"}:
            raise ValueError("device must be cpu or gpu")
        if not query_instruction.strip():
            raise ValueError("query_instruction must not be blank")
        self._model_path = Path(model_path).expanduser().resolve()
        self.model_name = model_name.strip()
        self.dimension = dimension
        self._batch_size = batch_size
        self._device = "cuda:0" if device == "gpu" else "cpu"
        self._query_instruction = query_instruction.strip()
        self._model_factory = model_factory
        self._injected_model: SentenceTransformerModel | None = None

    def _create_model(self) -> SentenceTransformerModel:
        if self._model_factory is None and not self._model_path.is_dir():
            raise EmbeddingError(f"Embedding model directory does not exist: {self._model_path}")
        factory = self._model_factory
        if factory is None:
            try:
                module = importlib.import_module("sentence_transformers")
                factory = cast(ModelFactory, module.SentenceTransformer)
            except (ImportError, AttributeError) as exc:
                raise EmbeddingError(
                    "sentence-transformers is not installed; install the 'embedding' extra"
                ) from exc
        try:
            model = factory(
                str(self._model_path),
                device=self._device,
                local_files_only=True,
            )
            actual_dimension = model.get_embedding_dimension()
        except Exception as exc:
            raise EmbeddingError(f"Unable to load embedding model: {self.model_name}") from exc
        if actual_dimension is not None and actual_dimension != self.dimension:
            raise EmbeddingError(
                "Embedding dimension mismatch: "
                f"configured {self.dimension}, model {actual_dimension}"
            )
        return model

    def _model(self) -> SentenceTransformerModel:
        if self._model_factory is not None:
            if self._injected_model is None:
                self._injected_model = self._create_model()
            return self._injected_model
        key = (str(self._model_path), self._device)
        model = self._models.get(key)
        if model is not None:
            return model
        with self._model_lock:
            model = self._models.get(key)
            if model is None:
                model = self._create_model()
                self._models[key] = model
        return model

    @staticmethod
    def _to_rows(value: object) -> list[object]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
            raise EmbeddingError("Embedding model returned a non-sequence result")
        return list(value)

    def _validate_vectors(self, value: object, expected_count: int) -> list[EmbeddingVector]:
        rows = self._to_rows(value)
        if len(rows) != expected_count:
            raise EmbeddingError(
                f"Embedding count mismatch: expected {expected_count}, received {len(rows)}"
            )
        vectors: list[EmbeddingVector] = []
        for row in rows:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                raise EmbeddingError("Embedding model returned an invalid vector")
            try:
                vector = [float(item) for item in row]
            except (TypeError, ValueError) as exc:
                raise EmbeddingError("Embedding vector contains a non-numeric value") from exc
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    "Embedding dimension mismatch: "
                    f"expected {self.dimension}, received {len(vector)}"
                )
            if not all(math.isfinite(item) for item in vector):
                raise EmbeddingError("Embedding vector contains a non-finite value")
            norm = math.sqrt(sum(item * item for item in vector))
            if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
                raise EmbeddingError(f"Embedding vector is not normalized: norm={norm:.6f}")
            vectors.append(vector)
        return vectors

    def _encode(self, texts: list[str]) -> list[EmbeddingVector]:
        try:
            result = self._model().encode(
                texts,
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Embedding inference failed") from exc
        return self._validate_vectors(result, len(texts))

    def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        """Embed chunks without a query instruction, preserving input order."""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("document texts must not contain blank values")
        return self._encode(texts)

    def embed_query(self, query: str) -> EmbeddingVector:
        """Embed one query with the BGE retrieval instruction."""
        stripped = query.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return self._encode([f"{self._query_instruction}{stripped}"])[0]

    @staticmethod
    def _sum_token_mask(mask: object) -> int:
        if hasattr(mask, "sum"):
            total = mask.sum()
            if hasattr(total, "item"):
                total = total.item()
            return int(total)
        if isinstance(mask, Iterable) and not isinstance(mask, (str, bytes, Mapping)):
            values = list(mask)
            if len(values) == 1 and isinstance(values[0], Iterable):
                return BgeEmbeddingProvider._sum_token_mask(values[0])
            return sum(int(value) for value in values)
        raise EmbeddingError("Tokenizer returned an invalid attention mask")

    def count_tokens(self, text: str) -> int:
        """Count non-padding tokens with the exact tokenizer loaded by the model."""
        stripped = text.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        try:
            tokenized = self._model().tokenize([stripped])
            mask = tokenized.get("attention_mask")
            if mask is None:
                raise EmbeddingError("Tokenizer result does not contain attention_mask")
            token_count = self._sum_token_mask(mask)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Unable to count embedding tokens") from exc
        if token_count <= 0:
            raise EmbeddingError("Tokenizer returned a non-positive token count")
        return token_count
