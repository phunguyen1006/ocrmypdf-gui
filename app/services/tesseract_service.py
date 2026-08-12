"""Tesseract-specific helpers: language list and validity checks."""
from __future__ import annotations

import logging

from app.services import dependency_checker

log = logging.getLogger("app.tesseract")

#: Language codes users see in the language dropdown (only when installed).
PREFERRED_LANGUAGES = ["vie", "eng", "chi_sim", "chi_tra", "jpn", "kor", "fra", "deu", "spa", "ita", "por", "rus"]


class TesseractService:
    """Cached access to installed Tesseract languages."""

    def __init__(self) -> None:
        self._languages: list[str] | None = None
        self._tesseract_path: str | None = None

    def refresh(self) -> list[str]:
        exe = dependency_checker._find_tesseract()
        self._tesseract_path = exe
        if not exe:
            self._languages = []
            return []
        langs = dependency_checker.list_languages(exe) or []
        self._languages = langs
        return langs

    def languages(self) -> list[str]:
        if self._languages is None:
            self.refresh()
        return self._languages or []

    def is_installed(self, code: str) -> bool:
        return code in self.languages()

    def installed_filtered(self, preferred: list[str] | None = None) -> list[str]:
        """Installed languages ordered with preferred ones first."""
        installed = set(self.languages())
        order = preferred or PREFERRED_LANGUAGES
        ordered = [lang for lang in order if lang in installed]
        ordered += sorted(installed - set(order))
        return ordered
