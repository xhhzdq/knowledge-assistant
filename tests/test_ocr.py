"""Unit tests for OCR modes, orchestration, and Paddle result normalization."""

from hashlib import sha256
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import (
    NoExtractableTextError,
    OcrError,
    UnsupportedDocumentTypeError,
)
from knowledge_assistant.processing.models import ParsedDocument, ParsedPage
from knowledge_assistant.processing.ocr import (
    PaddleOcrProvider,
    apply_pdf_ocr,
    parse_image_with_ocr,
    render_pdf_pages,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "week04"
HASH = "a" * 64


class FakeOcrProvider:
    provider_name = "fake-ocr"
    provider_version = "1.0"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[int | None] = []
        self.fail = fail

    def recognize(self, page_image: bytes, page_number: int | None) -> ParsedPage:
        self.calls.append(page_number)
        if self.fail:
            raise OcrError("fake model failed")
        return ParsedPage(page_number, f"OCR page {page_number}", "ocr", 0.8)


def parsed_pdf(*pages: ParsedPage) -> ParsedDocument:
    return ParsedDocument(list(pages), HASH, "pypdf", "6")


def fake_renderer(content: bytes, page_numbers: set[int]) -> dict[int, bytes]:
    assert content == b"pdf"
    return {page_number: f"page-{page_number}".encode() for page_number in page_numbers}


def test_auto_mode_only_recognizes_pages_marked_for_ocr() -> None:
    document = parsed_pdf(
        ParsedPage(1, "native text", "parser"),
        ParsedPage(2, "", "parser", requires_ocr=True),
    )
    provider = FakeOcrProvider()

    result = apply_pdf_ocr(document, b"pdf", provider, fake_renderer, mode="auto")

    assert provider.calls == [2]
    assert result.pages[0] == document.pages[0]
    assert result.pages[1].text == "OCR page 2"
    assert result.pages[1].source_type == "ocr"
    assert result.pages[1].ocr_confidence == pytest.approx(0.8)


def test_auto_mode_does_not_repeat_ocr_for_native_text_pdf() -> None:
    document = parsed_pdf(ParsedPage(1, "enough native text", "parser"))
    provider = FakeOcrProvider()

    result = apply_pdf_ocr(document, b"pdf", provider, fake_renderer)

    assert result is document
    assert provider.calls == []


def test_force_mode_recognizes_every_pdf_page() -> None:
    document = parsed_pdf(
        ParsedPage(1, "native one", "parser"),
        ParsedPage(2, "native two", "parser"),
    )
    provider = FakeOcrProvider()

    result = apply_pdf_ocr(document, b"pdf", provider, fake_renderer, mode="force")

    assert provider.calls == [1, 2]
    assert [page.source_type for page in result.pages] == ["ocr", "ocr"]


def test_never_mode_rejects_pdf_that_requires_ocr() -> None:
    document = parsed_pdf(ParsedPage(1, "", "parser", requires_ocr=True))

    with pytest.raises(OcrError, match="disabled"):
        apply_pdf_ocr(document, b"pdf", FakeOcrProvider(), fake_renderer, mode="never")


def test_model_failure_is_not_hidden() -> None:
    document = parsed_pdf(ParsedPage(1, "", "parser", requires_ocr=True))

    with pytest.raises(OcrError, match="fake model failed"):
        apply_pdf_ocr(
            document,
            b"pdf",
            FakeOcrProvider(fail=True),
            fake_renderer,
        )


def test_missing_rendered_page_is_an_explicit_error() -> None:
    document = parsed_pdf(ParsedPage(1, "", "parser", requires_ocr=True))

    with pytest.raises(OcrError, match="did not return page 1"):
        apply_pdf_ocr(document, b"pdf", FakeOcrProvider(), lambda _data, _pages: {})


def test_default_pdf_renderer_only_renders_requested_pages() -> None:
    content = (FIXTURE_DIR / "sample_two_page.pdf").read_bytes()

    rendered = render_pdf_pages(content, {2})

    assert set(rendered) == {2}
    assert rendered[2].startswith(b"\x89PNG\r\n\x1a\n")


def test_png_is_directly_recognized_as_one_page() -> None:
    content = (FIXTURE_DIR / "sample_ocr.png").read_bytes()
    provider = FakeOcrProvider()

    result = parse_image_with_ocr(content, "SAMPLE.PNG", provider)

    assert provider.calls == [1]
    assert result.pages[0].source_type == "ocr"
    assert result.content_hash == sha256(content).hexdigest()
    assert result.parser_name == "fake-ocr"


def test_image_never_mode_and_unsupported_extension_are_explicit() -> None:
    provider = FakeOcrProvider()
    with pytest.raises(OcrError, match="disabled"):
        parse_image_with_ocr(b"image", "scan.jpg", provider, mode="never")
    with pytest.raises(UnsupportedDocumentTypeError, match="does not support"):
        parse_image_with_ocr(b"image", "scan.gif", provider)


class FakePaddleResult:
    json = {
        "res": {
            "rec_texts": [" first line ", "", "second line"],
            "rec_scores": [1.2, -0.1, 0.75],
        }
    }


class FakePaddlePipeline:
    def __init__(self, results: list[object] | None = None, error: Exception | None = None):
        self.results = results if results is not None else [FakePaddleResult()]
        self.error = error

    def predict(self, input: object) -> list[object]:
        if self.error is not None:
            raise self.error
        return self.results


def test_paddle_adapter_normalizes_text_and_confidence() -> None:
    image = (FIXTURE_DIR / "sample_ocr.png").read_bytes()
    provider = PaddleOcrProvider(
        pipeline_factory=lambda **_kwargs: FakePaddlePipeline(),
        image_decoder=lambda data: data,
    )

    page = provider.recognize(image, 3)

    assert page.text == "first line\nsecond line"
    assert page.page_number == 3
    assert page.source_type == "ocr"
    assert page.ocr_confidence == pytest.approx((1.0 + 0.0 + 0.75) / 3)


def test_paddle_adapter_reuses_injected_pipeline_instance() -> None:
    image = (FIXTURE_DIR / "sample_ocr.png").read_bytes()
    initialization_count = 0

    def factory(**_kwargs: object) -> FakePaddlePipeline:
        nonlocal initialization_count
        initialization_count += 1
        return FakePaddlePipeline()

    provider = PaddleOcrProvider(
        pipeline_factory=factory,
        image_decoder=lambda data: data,
    )

    provider.recognize(image, 1)
    provider.recognize(image, 2)

    assert initialization_count == 1


def test_paddle_adapter_distinguishes_inference_failure_and_empty_result() -> None:
    image = (FIXTURE_DIR / "sample_ocr.png").read_bytes()
    failed = PaddleOcrProvider(
        pipeline_factory=lambda **_kwargs: FakePaddlePipeline(error=RuntimeError("boom")),
        image_decoder=lambda data: data,
    )
    empty = PaddleOcrProvider(
        pipeline_factory=lambda **_kwargs: FakePaddlePipeline(results=[]),
        image_decoder=lambda data: data,
    )

    with pytest.raises(OcrError, match="inference failed"):
        failed.recognize(image, 1)
    with pytest.raises(NoExtractableTextError, match="no extractable text"):
        empty.recognize(image, 1)


@pytest.mark.parametrize("mode", ["sometimes", "", "AUTO"])
def test_invalid_ocr_mode_is_rejected(mode: str) -> None:
    document = parsed_pdf(ParsedPage(1, "native", "parser"))

    with pytest.raises(ValueError, match="auto, never, or force"):
        apply_pdf_ocr(document, b"pdf", FakeOcrProvider(), fake_renderer, mode=mode)
