"""Tesseract discovery, catalogue access and app-private tessdata support."""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from app.services import dependency_checker
from app.services.language_service import (
    LanguageCatalog,
    LanguageDownloadService,
    LanguageModel,
    TesseractDataCache,
)

log = logging.getLogger("app.tesseract")

# Language codes that are useful to put near the top of the picker. The full
# official catalogue is still shown below these entries.
PREFERRED_LANGUAGES = [
    "vie",
    "eng",
    "chi_sim",
    "chi_tra",
    "jpn",
    "kor",
    "fra",
    "deu",
    "spa",
    "ita",
    "por",
    "rus",
]


class TesseractService:
    """Cached access to Tesseract, tessdata status and lazy downloads.

    Constructing this service reads only the bundled JSON catalogue. Network
    access is performed only by :meth:`ensure_languages`, normally from a
    background worker immediately before OCR starts.
    """

    def __init__(
        self,
        catalog: LanguageCatalog | None = None,
        cache: TesseractDataCache | None = None,
    ) -> None:
        self._languages: list[str] | None = None
        self._tesseract_path: str | None = None
        self.language_catalog = catalog or LanguageCatalog()
        self.cache = cache or TesseractDataCache()
        self.downloads = LanguageDownloadService(self.language_catalog, self.cache)

    def refresh(self) -> list[str]:
        exe = dependency_checker._find_tesseract()
        self._tesseract_path = exe
        self.cache.tesseract_exe = exe
        self.cache.sync_system_models()
        if not exe:
            langs = self._cached_codes()
        else:
            langs = dependency_checker.list_languages(exe, env=self.cache.runtime_env()) or []
            # A model downloaded during this session is available through the
            # merged cache even before a particular Tesseract build reports it.
            langs = sorted(set(langs).union(self._cached_codes()))
        self._languages = sorted(set(langs))
        return list(self._languages)

    def languages(self) -> list[str]:
        if self._languages is None:
            self.refresh()
        return list(self._languages or [])

    def is_installed(self, code: str) -> bool:
        return code in self.languages()

    def catalog_models(self) -> list[LanguageModel]:
        """Return the 126 official language models (not script models)."""
        return self.language_catalog.models("language")

    def catalog(self) -> list[LanguageModel]:
        """Public service API for the official language catalogue."""
        return self.catalog_models()

    def catalog_model(self, code: str) -> LanguageModel | None:
        return self.language_catalog.get(code)

    def status(self, code: str) -> str:
        """Return Installed, Cached or Available for a catalogue code."""
        return self.downloads.status(code)

    def statuses(self) -> dict[str, str]:
        return {model.code: self.status(model.code) for model in self.catalog_models()}

    def ensure_languages(
        self,
        codes: Iterable[str],
        *,
        cancel_event: Event | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[Path]:
        paths = self.downloads.ensure_languages(codes, cancel_event=cancel_event, progress=progress)
        self._languages = None
        return paths

    def runtime_env(self) -> dict[str, str]:
        """Return an environment with the merged app tessdata prefix."""
        return self.cache.runtime_env()

    def tesseract_path(self) -> str | None:
        if self._tesseract_path is None:
            self.refresh()
        return self._tesseract_path

    def installed_filtered(self, preferred: list[str] | None = None) -> list[str]:
        """Installed language codes ordered with preferred ones first."""
        installed = set(self.languages())
        order = preferred or PREFERRED_LANGUAGES
        ordered = [lang for lang in order if lang in installed]
        ordered += sorted(installed - set(order))
        return ordered

    def _cached_codes(self) -> list[str]:
        if not self.cache.tessdata_dir.is_dir():
            return []
        codes: list[str] = []
        for path in self.cache.tessdata_dir.rglob("*.traineddata"):
            relative = path.relative_to(self.cache.tessdata_dir).with_suffix("")
            codes.append(str(relative).replace("\\", "/"))
        return codes


class TesseractLanguageService(TesseractService):
    """Explicit name for callers focused on language management."""
