"""Detect external OCR components: OCRmyPDF, Tesseract, Ghostscript, tessdata.

The GUI never assumes these are installed. Every component is located on
disk and version-checked, and the result is reported in a friendly way.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("app.dependencies")

TESSERACT_PATHS: list[Path | str] = [
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
]

GS_PATTERN = re.compile(r"gswin(32|64)c\.exe")


@dataclass
class ComponentStatus:
    name: str
    present: bool = False
    version: str = ""
    path: str = ""
    error: str = ""

    def __str__(self) -> str:
        if self.present:
            return f"{self.name} {self.version}"
        return f"{self.name} missing"


@dataclass
class DependencyReport:
    ocrmypdf: ComponentStatus = field(default_factory=lambda: ComponentStatus("OCRmyPDF"))
    tesseract: ComponentStatus = field(default_factory=lambda: ComponentStatus("Tesseract"))
    ghostscript: ComponentStatus = field(default_factory=lambda: ComponentStatus("Ghostscript"))
    languages: dict[str, bool] = field(default_factory=dict)
    languages_error: str = ""

    @property
    def ok(self) -> bool:
        return self.ocrmypdf.present and self.tesseract.present

    @property
    def missing_names(self) -> list[str]:
        """Components required for the normal searchable-PDF workflow."""
        return [c.name for c in (self.ocrmypdf, self.tesseract) if not c.present]

    @property
    def optional_missing_names(self) -> list[str]:
        """Components used only by optional PDF/A or advanced paths."""
        return [self.ghostscript.name] if not self.ghostscript.present else []


def _run_version(cmd: list[str], timeout: float = 15.0) -> str | None:
    """Run a version command; return first version-looking line or None."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Command failed: %s (%s)", cmd, exc)
        return None
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in combined.splitlines():
        line = line.strip()
        if re.search(r"\d+\.\d+", line):
            return line
    return None


def _find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in TESSERACT_PATHS:
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return str(candidate_path)
    return None


def _find_ghostscript() -> str | None:
    found = shutil.which("gswin64c") or shutil.which("gswin32c")
    if found:
        return found
    gs_root = Path("C:/Program Files/gs")
    if gs_root.is_dir():
        try:
            versions = sorted(gs_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            versions = []
        for version_dir in versions:
            bin_dir = version_dir / "bin"
            if bin_dir.is_dir():
                for entry in bin_dir.iterdir():
                    if GS_PATTERN.match(entry.name):
                        return str(entry)
    return None


def _run_ocrmypdf_version() -> str | None:
    try:
        import ocrmypdf

        return f"v{ocrmypdf.__version__}"
    except ImportError:
        return None


def _run_gs_version(exe: str) -> str | None:
    return _run_version([exe, "--version"])


def _run_tesseract_version(exe: str) -> str | None:
    return _run_version([exe, "--version"])


def list_languages(exe: str) -> list[str] | None:
    """Return installed tessdata language codes (eng, vie, ...)."""
    try:
        proc = subprocess.run(
            [exe, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=20.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("tesseract --list-langs failed: %s", exc)
        return None
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    langs: list[str] = []
    started = False
    for line in combined.splitlines():
        line = line.strip()
        if not line:
            continue
        if not started:
            if line.startswith("List of available languages"):
                started = True
            continue
        langs.append(line)
    return langs or None


def check_dependencies() -> DependencyReport:
    """Run the full dependency check."""
    report = DependencyReport()

    ocrmypdf_version = _run_ocrmypdf_version()
    report.ocrmypdf.present = ocrmypdf_version is not None
    report.ocrmypdf.version = ocrmypdf_version or ""

    tesseract_exe = _find_tesseract()
    if tesseract_exe:
        version = _run_tesseract_version(tesseract_exe)
        report.tesseract.present = True
        report.tesseract.version = version or "unknown"
        report.tesseract.path = tesseract_exe
        langs = list_languages(tesseract_exe)
        if langs is None:
            report.languages_error = "Could not read the list of installed OCR languages."
        else:
            report.languages = {lang: True for lang in langs}
    else:
        report.tesseract.error = (
            "Tesseract OCR was not found.\n"
            'Install Tesseract 5.x from https://github.com/UB-Mannheim/tesseract/wiki '
            'and tick "Add to PATH" (or pick English + Vietnamese language packs).'
        )

    gs_exe = _find_ghostscript()
    if gs_exe:
        gs_version = _run_gs_version(gs_exe)
        report.ghostscript.present = True
        report.ghostscript.version = gs_version or "unknown"
        report.ghostscript.path = gs_exe
    else:
        report.ghostscript.error = (
            "Ghostscript was not found.\n"
            "It is needed to create PDF/A files and for some PDF optimizations. "
            "Install it from https://ghostscript.com/releases/gsdnld.html"
        )

    return report


def human_language_name(code: str) -> str:
    names = {
        "eng": "English",
        "vie": "Vietnamese",
        "chi_sim": "Chinese (Simplified)",
        "chi_tra": "Chinese (Traditional)",
        "jpn": "Japanese",
        "kor": "Korean",
        "fra": "French",
        "deu": "German",
        "spa": "Spanish",
        "ita": "Italian",
        "por": "Portuguese",
        "rus": "Russian",
        "ara": "Arabic",
        "tha": "Thai",
        "ind": "Indonesian",
        "mal": "Malayalam",
        "hin": "Hindi",
        "osd": "Orientation and script detection",
    }
    return names.get(code, code)
