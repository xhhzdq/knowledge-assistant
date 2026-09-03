"""PaddleOCR 3.x adapter with lazy, process-wide model reuse."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Mapping
from threading import Lock
from typing import ClassVar, Protocol, cast

from knowledge_assistant.exceptions import NoExtractableTextError, OcrError
from knowledge_assistant.processing.models import ParsedPage
from knowledge_assistant.processing.ocr.base import require_recognized_text


class PaddlePipeline(Protocol):
    """Small subset of the PaddleOCR pipeline used by this adapter."""

    def predict(self, input: object) -> Iterable[object]:
        """Run OCR for one decoded image."""
        ...


PipelineFactory = Callable[..., PaddlePipeline]
ImageDecoder = Callable[[bytes], object]


class PaddleOcrProvider:
    """CPU/GPU PaddleOCR provider whose heavy pipeline is loaded only on first use."""

    provider_name = "paddleocr"
    _pipelines: ClassVar[dict[tuple[str, str], PaddlePipeline]] = {}
    _pipeline_lock: ClassVar[Lock] = Lock()

    def __init__(
        self,
        device: str = "cpu",
        language: str = "ch",
        pipeline_factory: PipelineFactory | None = None,
        image_decoder: ImageDecoder | None = None,
    ) -> None:
        if device not in {"cpu", "gpu"}:
            raise ValueError("PaddleOCR device must be cpu or gpu")
        if not language.strip():
            raise ValueError("PaddleOCR language must not be blank")
        self._device = "gpu:0" if device == "gpu" else "cpu"
        self._language = language.strip()
        self._pipeline_factory = pipeline_factory
        self._image_decoder = image_decoder or self._decode_image
        self._injected_pipeline: PaddlePipeline | None = None

    @property
    def provider_version(self) -> str:
        """Return the installed adapter version without forcing model initialization."""
        try:
            module = importlib.import_module("paddleocr")
        except ImportError:
            return "unavailable"
        return str(getattr(module, "__version__", "unknown"))

    def _create_pipeline(self) -> PaddlePipeline:
        factory = self._pipeline_factory
        if factory is None:
            try:
                module = importlib.import_module("paddleocr")
                factory = cast(PipelineFactory, module.PaddleOCR)
            except (ImportError, AttributeError) as exc:
                raise OcrError(
                    "PaddleOCR is not installed; install the project's 'ocr' extra"
                ) from exc
        try:
            return factory(
                device=self._device,
                lang=self._language,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        except Exception as exc:
            raise OcrError("Unable to initialize the PaddleOCR model") from exc

    def _pipeline(self) -> PaddlePipeline:
        if self._pipeline_factory is not None:
            if self._injected_pipeline is None:
                self._injected_pipeline = self._create_pipeline()
            return self._injected_pipeline
        key = (self._device, self._language)
        pipeline = self._pipelines.get(key)
        if pipeline is not None:
            return pipeline
        with self._pipeline_lock:
            pipeline = self._pipelines.get(key)
            if pipeline is None:
                pipeline = self._create_pipeline()
                self._pipelines[key] = pipeline
        return pipeline

    @staticmethod
    def _decode_image(page_image: bytes) -> object:
        if not page_image:
            raise OcrError("OCR image bytes must not be empty")
        try:
            image_module = importlib.import_module("PIL.Image")
            numpy_module = importlib.import_module("numpy")
            bytes_io = importlib.import_module("io").BytesIO(page_image)
            with image_module.open(bytes_io) as image:
                return numpy_module.asarray(image.convert("RGB"))
        except Exception as exc:
            raise OcrError("Unable to decode the OCR page image") from exc

    @staticmethod
    def _result_payload(result: object) -> Mapping[str, object]:
        payload = getattr(result, "json", result)
        if callable(payload):
            payload = payload()
        if not isinstance(payload, Mapping):
            raise OcrError("PaddleOCR returned an unsupported result format")
        inner = payload.get("res", payload)
        if not isinstance(inner, Mapping):
            raise OcrError("PaddleOCR result does not contain a result payload")
        return cast(Mapping[str, object], inner)

    @staticmethod
    def _as_texts(value: object) -> list[str]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
            return []
        return [str(item) for item in value]

    @staticmethod
    def _as_scores(value: object) -> list[float]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
            return []
        scores: list[float] = []
        for item in value:
            try:
                score = float(item)
            except (TypeError, ValueError):
                continue
            scores.append(min(1.0, max(0.0, score)))
        return scores

    def recognize(self, page_image: bytes, page_number: int | None) -> ParsedPage:
        """Decode an image, execute PaddleOCR, and normalize text/confidence."""
        try:
            image = self._image_decoder(page_image)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError("Unable to decode the OCR page image") from exc
        try:
            results = list(self._pipeline().predict(image))
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError("PaddleOCR inference failed") from exc
        if not results:
            raise NoExtractableTextError("OCR found no extractable text in the page image")

        texts: list[str] = []
        scores: list[float] = []
        for result in results:
            payload = self._result_payload(result)
            texts.extend(self._as_texts(payload.get("rec_texts")))
            scores.extend(self._as_scores(payload.get("rec_scores")))
        text = require_recognized_text(texts, "page image")
        confidence = sum(scores) / len(scores) if scores else None
        return ParsedPage(
            page_number=page_number,
            text=text,
            source_type="ocr",
            ocr_confidence=confidence,
            requires_ocr=False,
        )
