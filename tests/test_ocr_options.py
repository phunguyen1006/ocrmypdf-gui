from __future__ import annotations

from pathlib import Path

from app.core.ocr_options import build_options, languages_for_settings, preset_overrides
from app.models.settings import AppSettings, OcrPreset


def test_languages_for_settings() -> None:
    assert languages_for_settings(AppSettings(language_preset="vie+eng")) == ["vie", "eng"]
    assert languages_for_settings(AppSettings(language_preset="custom", custom_languages=["deu", "eng"])) == ["deu", "eng"]


def test_presets_are_explicit() -> None:
    assert preset_overrides(OcrPreset.QUICK.value)["rotate_pages"] is False
    assert preset_overrides(OcrPreset.DIFFICULT.value)["oversample"] is True


def test_build_options_uses_real_ocrmypdf_api(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"%PDF-1.4\n")
    work = tmp_path / "work"
    work.mkdir()
    settings = AppSettings(
        language_preset="eng",
        page_selection_mode="range",
        tesseract_timeout=0,
    )
    options, selected_work = build_options(
        input_path=input_path,
        settings=settings,
        output_path=tmp_path / "output.pdf",
        pages=[1, 2],
        work_folder=work,
    )
    assert selected_work == work
    assert options.languages == ["eng"]
    assert options.pages == {1, 2}
    assert options.tesseract_timeout is None
    assert options.output_type == "auto"


def test_difficult_preset_uses_ocrmypdf_oversample_value(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"%PDF-1.4\n")
    work = tmp_path / "work"
    work.mkdir()
    settings = AppSettings(language_preset="eng", preset=OcrPreset.DIFFICULT.value)

    options, _ = build_options(
        input_path=input_path,
        settings=settings,
        output_path=tmp_path / "output.pdf",
        work_folder=work,
    )

    assert options.oversample == 300


def test_build_options_accepts_mixed_language_document(tmp_path: Path) -> None:
    input_path = tmp_path / "mixed.pdf"
    input_path.write_bytes(b"%PDF-1.4\n")
    work = tmp_path / "work"
    work.mkdir()
    settings = AppSettings(
        language_preset="custom",
        custom_languages=["vie", "chi_sim"],
        rotate_pages=False,
        deskew=False,
    )

    options, _ = build_options(
        input_path=input_path,
        settings=settings,
        output_path=tmp_path / "output.pdf",
        work_folder=work,
    )

    assert options.languages == ["vie", "chi_sim"]
