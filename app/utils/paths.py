"""Path helpers: output naming, unique names, temp dirs, long paths.

File safety rules implemented here:
- input files are never modified (worker always writes a new output)
- output is never silently overwritten (unique suffix is appended)
- all paths are handled with pathlib.Path
- Unicode (Vietnamese) filenames and spaces are supported
"""
from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

APP_NAME = "OCRmyPDF-GUI"

OUTPUT_SUFFIX = " (OCR)"


def app_data_dir() -> Path:
    """User-scoped directory for logs, history and temp data."""
    override = os.environ.get("OCRMY_PDF_GUI_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def app_log_dir() -> Path:
    return app_data_dir() / "logs"


def app_temp_dir() -> Path:
    return app_data_dir() / "tmp"


def ensure_app_dirs() -> None:
    for d in (app_data_dir(), app_log_dir(), app_temp_dir()):
        d.mkdir(parents=True, exist_ok=True)


def long_path(path: Path | str) -> str:
    """Return a path usable when total length exceeds Windows' 260 char limit."""
    p = Path(path)
    if os.name == "nt" and len(str(p.resolve())) >= 240:
        return "\\\\?\\" + str(p.resolve())
    return str(p)


def output_name_for(input_path: Path, suffix: str = OUTPUT_SUFFIX) -> str:
    """input.pdf -> 'input (OCR).pdf' (keeps the full stem, Unicode-safe)."""
    return f"{input_path.stem}{suffix}{input_path.suffix}"


def unique_output_path(
    input_path: Path,
    *,
    suffix: str = OUTPUT_SUFFIX,
    reserved_paths: Iterable[Path | str] | None = None,
) -> Path:
    """Return an output path that does not exist yet.

    input.pdf            -> input (OCR).pdf
    input (OCR).pdf (exists) -> input (OCR 2).pdf
    Never overwrites silently.
    """
    reserved = {
        os.path.normcase(os.path.abspath(str(Path(path))))
        for path in (reserved_paths or [])
    }

    def is_taken(path: Path) -> bool:
        return path.exists() or os.path.normcase(os.path.abspath(str(path))) in reserved

    out = input_path.with_name(output_name_for(input_path, suffix))
    counter = 2
    while is_taken(out):
        if suffix == OUTPUT_SUFFIX:
            name = f"{input_path.stem} (OCR {counter}){input_path.suffix}"
        else:
            name = f"{input_path.stem}{suffix} {counter}{input_path.suffix}"
        out = input_path.with_name(name)
        counter += 1
    return out


_TEMP_PREFIX = re.compile(r"^ocr-tmp-")


def make_work_dir() -> Path:
    """Create a per-job temporary directory that the worker cleans up."""
    ensure_app_dirs()
    d = Path(tempfile.mkdtemp(prefix="ocr-tmp-", dir=app_temp_dir()))
    return d


def is_work_dir_candidate(path: Path) -> bool:
    return _TEMP_PREFIX.match(path.name) is not None
