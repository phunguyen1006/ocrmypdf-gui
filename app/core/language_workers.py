"""Qt workers for non-blocking language detection and model downloads."""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from app.services.language_detection_service import (
    DetectionCancelled,
    DocumentDetection,
    LanguageDetectionService,
)
from app.services.language_service import DownloadCancelled, LanguageServiceError
from app.services.tesseract_service import TesseractService

log = logging.getLogger("app.language_workers")


class LanguageDetectionWorker(QObject):
    """Run one or more document detections away from the Qt GUI thread."""

    progress = Signal(int, int, str)
    finished = Signal(object)  # dict[str, DocumentDetection]
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, jobs: list[tuple[str, Path, list[int] | None]], service: LanguageDetectionService) -> None:
        super().__init__()
        self.jobs = jobs
        self.service = service
        self.cancel_event = Event()

    @Slot()
    def run(self) -> None:
        results: dict[str, DocumentDetection] = {}
        try:
            total = len(self.jobs)
            for index, (job_id, path, pages) in enumerate(self.jobs, start=1):
                if self.cancel_event.is_set():
                    raise DetectionCancelled("Language detection cancelled.")

                def report(_current: int, _page_total: int, message: str) -> None:
                    self.progress.emit(index, total, message)

                results[job_id] = self.service.detect_document(
                    path,
                    pages,
                    cancel_event=self.cancel_event,
                    progress=report,
                )
            self.finished.emit(results)
        except DetectionCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surface worker failures to GUI
            log.exception("Language detection failed")
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.cancel_event.set()


class LanguageDownloadWorker(QObject):
    """Download missing language models without blocking the main window."""

    progress = Signal(str, int, int)
    finished = Signal(object)  # list[Path]
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, service: TesseractService, codes: list[str]) -> None:
        super().__init__()
        self.service = service
        self.codes = codes
        self.cancel_event = Event()

    @Slot()
    def run(self) -> None:
        try:
            paths = self.service.ensure_languages(
                self.codes,
                cancel_event=self.cancel_event,
                progress=lambda code, current, total: self.progress.emit(code, current, total),
            )
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.finished.emit(paths)
        except DownloadCancelled:
            self.cancelled.emit()
        except LanguageServiceError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Language download failed")
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.cancel_event.set()
