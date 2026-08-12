"""Build OCRmyPDF OcrOptions from app settings + job definition.

Uses the official Python API (OcrOptions pydantic model) instead of
building a huge command string. Presets are defined here.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ocrmypdf import OcrOptions

from app.models.settings import (
    AppSettings,
    LanguagePreset,
    OcrMode,
    OcrPreset,
    Optimization,
    OutputType,
)
from app.utils.paths import make_work_dir, unique_output_path


def languages_for_settings(settings: AppSettings) -> list[str]:
    """Resolve the language preset into a list of tessdata language codes."""
    if settings.language_preset == LanguagePreset.AUTO.value:
        raise ValueError("Auto detect must be resolved before OCR starts.")
    if settings.language_preset == LanguagePreset.CUSTOM.value:
        langs = [l.strip() for l in settings.custom_languages if l.strip()]
        return langs or ["eng"]
    return [l for l in settings.language_preset.split("+") if l]


def resolve_output_path(
    input_path: Path,
    settings: AppSettings,
    reserved_paths: Iterable[Path | str] | None = None,
) -> Path:
    """Pick the final output location (unique name, never overwrite)."""
    if settings.output_folder_mode == "custom" and settings.output_folder.strip():
        folder = Path(settings.output_folder.strip())
    else:
        folder = input_path.parent
    candidate = folder / input_path.name
    return unique_output_path(candidate, reserved_paths=reserved_paths)


def preset_overrides(preset: str) -> dict:
    """Settings that change when the user switches preset combo."""
    if preset == OcrPreset.QUICK.value:
        return {
            "rotate_pages": False,
            "deskew": False,
            "oversample": False,
            "optimize": Optimization.NONE.value,
            "tesseract_timeout": 60,
        }
    if preset == OcrPreset.DIFFICULT.value:
        return {
            "rotate_pages": True,
            "deskew": True,
            "oversample": True,
            "optimize": Optimization.STANDARD.value,
            "tesseract_timeout": 300,
        }
    return {  # standard (default)
        "rotate_pages": True,
        "deskew": True,
        "oversample": False,
        "optimize": Optimization.STANDARD.value,
        "tesseract_timeout": 180,
    }


def build_options(
    *,
    input_path: Path,
    settings: AppSettings,
    output_path: Path,
    pages: list[int] | None = None,
    work_folder: Path | None = None,
    sidecar_path: Path | None = None,
) -> tuple[OcrOptions, Path]:
    """Build OcrOptions for a job, returning (options, chosen_work_dir).

    Raises ValueError if the settings combination is invalid.
    """
    if not input_path.exists():
        raise ValueError(f"Input file does not exist: {input_path}")

    languages = languages_for_settings(settings)
    if not languages:
        raise ValueError("No OCR language selected.")

    overrides = preset_overrides(settings.preset)
    optimize = settings.optimize
    timeout = settings.tesseract_timeout

    # Quick and Difficult are opinionated presets. Standard intentionally
    # respects the two main checkboxes so a user can turn either one off.
    rotate = settings.rotate_pages
    deskew = settings.deskew
    oversample = 300 if settings.oversample else 0
    if settings.preset == OcrPreset.QUICK.value:
        rotate = False
        deskew = False
        oversample = 0
        optimize = overrides["optimize"]
        timeout = overrides["tesseract_timeout"]
    elif settings.preset == OcrPreset.DIFFICULT.value:
        rotate = True
        deskew = True
        oversample = 300
        optimize = overrides["optimize"]
        timeout = overrides["tesseract_timeout"]

    if settings.ocr_mode == OcrMode.REDO.value:
        # ocrmypdf rejects these combos with --mode redo
        rotate = False
        deskew = False

    jobs = settings.jobs
    if settings.jobs == 0:
        jobs = None  # ocrmypdf default

    page_value = set(pages) if pages is not None else None
    timeout_value = float(timeout) if timeout > 0 else None

    if work_folder is None:
        work_folder = make_work_dir()

    options = OcrOptions(
        input_file=input_path,
        output_file=output_path,
        languages=languages,
        deskew=deskew,
        rotate_pages=rotate,
        oversample=oversample,
        mode=settings.ocr_mode,
        optimize=int(Optimization(optimize).value),
        tesseract_timeout=timeout_value,
        jobs=jobs,
        use_threads=settings.run_in_threads,
        pages=page_value,
        sidecar=sidecar_path,
        output_type=settings.output_type,
        no_overwrite=True,
        progress_bar=True,
        quiet=True,
        work_folder=work_folder,
        title=f"OCRmyPDF GUI - {input_path.name}",  # informational only
    )
    return options, work_folder


def estimate_job_work(settings: AppSettings, page_selection: list[int] | None, page_count: int) -> int:
    """Total units shown in the progress bar (for ETA)."""
    if page_selection is not None:
        return len(page_selection)
    return max(page_count, 1)
