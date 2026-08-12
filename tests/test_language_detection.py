from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.language_detection_service import DocumentDetection, LanguageDetectionService, PageDetection
from app.services.tesseract_service import TesseractService


def test_infer_simplified_chinese_and_vietnamese_without_network(tmp_path: Path) -> None:
    service = LanguageDetectionService(TesseractService(), tmp_path / "cache")
    chinese = "".join(map(chr, [0x8FD9, 0x662F, 0x4E00, 0x4E2A, 0x4E2D, 0x6587, 0x6D4B, 0x8BD5, 0x9875, 0x9762]))
    languages, confidence, candidates = service._infer_languages(
        chinese,
        "",
        ["vie", "eng", "chi_sim", "chi_tra"],
    )
    assert languages == ["chi_sim"]
    assert confidence > 0
    assert candidates == []


def test_low_confidence_detection_requires_review(tmp_path: Path) -> None:
    page = PageDetection(1, ("vie",), 0.4, "latin")
    detection = DocumentDetection(("vie",), 0.4, (page,))
    assert detection.needs_review is True


@pytest.mark.integration
def test_detect_mixed_vietnamese_simplified_chinese_pdf(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    import img2pdf

    tesseract = TesseractService()
    if not tesseract.tesseract_path():
        pytest.skip("Tesseract is not installed")
    font_vie = Path(r"C:\Windows\Fonts\arial.ttf")
    font_chi = Path(r"C:\Windows\Fonts\simsun.ttc")
    if not font_vie.exists() or not font_chi.exists():
        pytest.skip("Windows test fonts are not installed")

    chinese = "".join(
        map(
            chr,
            [
                0x8FD9,
                0x662F,
                0x4E00,
                0x4E2A,
                0x4E2D,
                0x6587,
                0x6D4B,
                0x8BD5,
                0x9875,
                0x9762,
                0x3002,
                0x4E2D,
                0x534E,
                0x4EBA,
                0x6C11,
                0x5171,
                0x548C,
                0x56FD,
            ],
        )
    )
    images: list[bytes] = []
    vietnamese = "Xin chào Việt Nam. Đây là một trang tiếng Việt."
    for text, font_path in ((vietnamese, font_vie), (chinese, font_chi)):
        image = Image.new("RGB", (1600, 1000), "white")
        draw = ImageDraw.Draw(image)
        draw.text((100, 200), text, font=ImageFont.truetype(str(font_path), 72), fill="black")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        images.append(stream.getvalue())
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(img2pdf.convert(images))

    result = LanguageDetectionService(tesseract, tmp_path / "language-cache").detect_document(pdf_path)
    assert "vie" in result.languages
    assert "chi_sim" in result.languages
    assert result.page_results[0].page == 1
    assert result.page_results[1].page == 2

    cached_detector = LanguageDetectionService(tesseract, tmp_path / "language-cache")
    cached_detector._detect_page = lambda *_args: (_ for _ in ()).throw(AssertionError("page was not cached"))  # type: ignore[method-assign]
    cached_result = cached_detector.detect_document(pdf_path)
    assert cached_result.languages == result.languages
    assert all(page.cached for page in cached_result.page_results)


def test_detection_rejects_missing_pdf(tmp_path: Path) -> None:
    service = LanguageDetectionService(TesseractService(), tmp_path / "cache")
    with pytest.raises(Exception, match="PDF not found"):
        service.detect_document(tmp_path / "missing.pdf")
