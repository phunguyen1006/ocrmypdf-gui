"""Application settings model and persistence (QSettings-backed)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path


class LanguagePreset(str, Enum):
    AUTO = "auto"
    VIETNAMESE = "vie"
    ENGLISH = "eng"
    VIETNAMESE_ENGLISH = "vie+eng"
    CUSTOM = "custom"


class OcrMode(str, Enum):
    SKIP = "skip"
    REDO = "redo"
    FORCE = "force"


class OcrPreset(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DIFFICULT = "difficult"


class OutputType(str, Enum):
    AUTO = "auto"
    PDF = "pdf"
    PDFA = "pdfa"


class Optimization(str, Enum):
    NONE = "0"
    STANDARD = "1"
    HIGH = "2"
    MAXIMUM = "3"


class OutputFolderMode(str, Enum):
    SAME = "same"
    CUSTOM = "custom"


class PageSelectionMode(str, Enum):
    ALL = "all"
    RANGE = "range"


@dataclass
class AppSettings:
    """Snapshot of user preferences. Persisted via QSettings."""

    language_preset: str = LanguagePreset.AUTO.value
    custom_languages: list[str] = field(default_factory=lambda: ["vie", "eng"])
    preset: str = OcrPreset.STANDARD.value
    rotate_pages: bool = True
    deskew: bool = True
    oversample: bool = False

    ocr_mode: str = OcrMode.SKIP.value
    tesseract_timeout: int = 180  # seconds per page
    page_selection_mode: str = PageSelectionMode.ALL.value
    page_range: str = ""
    exclude_pages: str = ""

    output_folder_mode: str = OutputFolderMode.SAME.value
    output_folder: str = ""

    optimize: str = Optimization.STANDARD.value
    output_type: str = OutputType.AUTO.value
    sidecar: bool = False
    jobs: int = 0  # 0 = auto
    concurrent_files: int = 1
    # ocrmypdf 17.x resolves plugin option namespaces lazily via module globals
    # that are absent in spawned child processes; thread-based parallelism is
    # required for rotate_pages/deskew to work in API mode. The GUI already
    # isolates OCR in its own worker process, so threads are safe here.
    run_in_threads: bool = True

    # Language packs are downloaded lazily into the user-scoped tessdata
    # cache. Existing settings files do not contain this key, so the default
    # preserves compatibility with older JSON snapshots.
    auto_download_languages: bool = True

    theme: str = "auto"
    lang_installed_cache: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        # lang_installed_cache is transient, do not persist.
        data.pop("lang_installed_cache", None)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        defaults = cls()

        def _enum_value(name: str, enum_type: type[Enum]) -> None:
            value = filtered.get(name, getattr(defaults, name))
            allowed = {member.value for member in enum_type}
            filtered[name] = value if value in allowed else getattr(defaults, name)

        _enum_value("language_preset", LanguagePreset)
        _enum_value("preset", OcrPreset)
        _enum_value("ocr_mode", OcrMode)
        _enum_value("output_type", OutputType)
        _enum_value("optimize", Optimization)
        _enum_value("output_folder_mode", OutputFolderMode)
        _enum_value("page_selection_mode", PageSelectionMode)

        languages = filtered.get("custom_languages", defaults.custom_languages)
        if isinstance(languages, str):
            languages = languages.replace(",", "+").split("+")
        elif not isinstance(languages, list):
            languages = defaults.custom_languages
        filtered["custom_languages"] = [str(language).strip() for language in languages if str(language).strip()]
        if not filtered["custom_languages"]:
            filtered["custom_languages"] = ["eng"]

        for name in ("tesseract_timeout", "jobs", "concurrent_files"):
            try:
                filtered[name] = int(filtered.get(name, getattr(defaults, name)))
            except (TypeError, ValueError):
                filtered[name] = getattr(defaults, name)
        filtered["tesseract_timeout"] = max(0, filtered["tesseract_timeout"])
        filtered["jobs"] = max(0, filtered["jobs"])
        filtered["concurrent_files"] = min(4, max(1, filtered["concurrent_files"]))

        for name in (
            "rotate_pages",
            "deskew",
            "oversample",
            "sidecar",
            "run_in_threads",
            "auto_download_languages",
        ):
            value = filtered.get(name, getattr(defaults, name))
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "yes", "on"}
            filtered[name] = bool(value)

        return cls(**filtered)


class SettingsStore:
    """QSettings wrapper with sane defaults.

    Used by the GUI; can also be constructed with a custom file for tests.
    """

    def __init__(self, organization: str = "OCRmyPDF GUI", application: str = "OCRmyPDF GUI", ini_path: Path | None = None):
        from PySide6.QtCore import QSettings  # local import: Qt only needed in GUI

        if ini_path is not None:
            # Test mode: isolated file-backed settings.
            self._settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
        else:
            self._settings = QSettings(organization, application)

    def load(self) -> AppSettings:
        raw = self._settings.value("app_settings", "", str)
        if raw:
            try:
                return AppSettings.from_dict(json.loads(raw))
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self._settings.setValue("app_settings", settings.to_json())
        self._settings.sync()

    def first_run_done(self) -> bool:
        return self._settings.value("first_run_done", False, bool)

    def set_first_run_done(self, value: bool = True) -> None:
        self._settings.setValue("first_run_done", value)
        self._settings.sync()

    def error_counter(self) -> int:
        return self._settings.value("error_counter", 0, int)

    def set_error_counter(self, value: int) -> None:
        self._settings.setValue("error_counter", value)

    def window_geometry(self) -> bytes | None:
        data = self._settings.value("window_geometry")
        return data if isinstance(data, bytes) else None

    def set_window_geometry(self, data: bytes) -> None:
        self._settings.setValue("window_geometry", data)
