"""PDF inspection: page count, size, existing text detection."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("app.pdf")


@dataclass
class PdfInfo:
    pages: int = 0
    size_bytes: int = 0
    has_text: bool = False
    encrypted: bool = False
    error: str = ""

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def inspect_pdf(path: Path) -> PdfInfo:
    """Gather basic metadata. Never raises; errors are captured in the result."""
    info = PdfInfo()
    try:
        info.size_bytes = path.stat().st_size
    except OSError as exc:
        info.error = f"Cannot read file: {exc}"
        return info

    import pikepdf

    try:
        with pikepdf.open(path, password="") as pdf:
            info.pages = len(pdf.pages)
            info.encrypted = pdf.is_encrypted
            info.has_text = _has_text(pdf)
    except pikepdf.PasswordError:
        info.encrypted = True
        info.error = "This PDF is password-protected."
    except pikepdf.PdfError as exc:
        info.error = f"This file does not look like a valid PDF: {exc}"
    except Exception as exc:  # noqa: BLE001
        info.error = f"Could not analyze PDF: {exc}"
    return info


def _has_text(pdf) -> bool:
    """Heuristic: a searchable PDF usually embeds fonts and content streams."""
    for page in pdf.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        font = resources.get("/Font")
        if font is not None and len(font) > 0:
            return True
    return False