"""Main application window."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QDialog,
    QApplication,
)

from app.core.queue_manager import QueueManager
from app.core.language_workers import LanguageDownloadWorker, LanguageDetectionWorker
from app.core.page_ranges import (
    parse_spec_to_pages,
    validate_spec,
)
from app.core.ocr_options import effective_settings_for_document, resolve_output_path
from app.models.job import Job, JobStatus
from app.models.settings import AppSettings, OcrPreset, SettingsStore
from app.services import dependency_checker
from app.services.history_service import HistoryService
from app.services.language_detection_service import DocumentDetection, LanguageDetectionService
from app.services.pdf_service import inspect_pdf
from app.services.tesseract_service import TesseractService
from app.ui.drop_zone import DropZone
from app.ui.first_run_dialog import FirstRunDialog
from app.ui.history_dialog import HistoryDialog
from app.ui.job_widget import JobWidget
from app.ui.language_dialog import LanguagePickerDialog, LanguageReviewDialog
from app.ui.log_panel import LogPanel
from app.ui.progress_panel import ProgressPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import apply_monochrome_theme
from app.utils.paths import long_path
from app.utils.resources import resource_path

log = logging.getLogger("app.main_window")

PRESET_LABELS = {
    OcrPreset.QUICK.value: "Quick",
    OcrPreset.STANDARD.value: "Standard",
    OcrPreset.DIFFICULT.value: "Difficult Scan",
}

LANGUAGE_LABELS = {
    "auto": "Auto detect — adaptive pages",
    "chi_sim+vie": "Chinese (Simplified) + Vietnamese",
    "vie": "Vietnamese",
    "eng": "English",
    "vie+eng": "Vietnamese + English",
    "custom": "Choose multiple languages…",
}


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore | None = None, history: HistoryService | None = None) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            apply_monochrome_theme(app)
        self.setWindowTitle("OCRmyPDF GUI")
        icon_path = resource_path("assets/ocrmypdf-gui.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(760, 640)
        self.resize(940, 780)

        self.store = store or SettingsStore()
        self.settings: AppSettings = self.store.load()
        self.tesseract = TesseractService()
        self.history = history or HistoryService()
        self._language_thread: QThread | None = None
        self._language_worker = None
        self._preflight_waiting: list[Job] = []
        self._detected_results: dict[str, DocumentDetection] = {}
        self._resolved_languages: dict[str, list[str]] = {}
        self._preparing_languages = False
        self._language_generation = 0

        self.queue = QueueManager(self)
        self.queue.set_concurrency(self.settings.concurrent_files)
        self.queue.job_updated.connect(self._on_job_updated)
        self.queue.job_finished.connect(self._on_job_finished)
        self.queue.queue_progress.connect(self._on_queue_progress)
        self.queue.worker_log.connect(self._on_worker_log)
        self.queue.status_changed.connect(self._on_status_changed)

        self._build_ui()
        self._load_window_state()

        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(1000)
        self._eta_timer.timeout.connect(self._tick)
        self._eta_timer.start()

        QTimer.singleShot(0, self._after_start)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(16)

        # Top bar
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        eyebrow = QLabel("DESKTOP OCR UTILITY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("OCRmyPDF GUI")
        title.setObjectName("appTitle")
        subtitle = QLabel("Turn scanned PDFs into searchable documents.")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(eyebrow)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top.addLayout(title_box)
        top.addStretch()

        self.history_btn = QPushButton("History")
        self.history_btn.setObjectName("quietButton")
        self.history_btn.clicked.connect(self._open_history)
        self.log_btn = QPushButton("Log")
        self.log_btn.setObjectName("quietButton")
        self.log_btn.setCheckable(True)
        self.log_btn.clicked.connect(self._toggle_log)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("quietButton")
        self.settings_btn.clicked.connect(self._open_settings)
        for btn in (self.history_btn, self.log_btn, self.settings_btn):
            top.addWidget(btn)
        root.addLayout(top)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        root.addWidget(self.drop_zone)

        # Queue card
        queue_card = QFrame()
        queue_card.setObjectName("card")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(16, 14, 16, 10)
        queue_layout.setSpacing(8)
        queue_header = QHBoxLayout()
        files_title = QLabel("Files")
        files_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        queue_header.addWidget(files_title)
        self.queue_count_label = QLabel("0 files")
        self.queue_count_label.setObjectName("mutedLabel")
        queue_header.addWidget(self.queue_count_label)
        queue_header.addStretch()
        self.clear_finished_btn = QPushButton("Clear finished")
        self.clear_finished_btn.setObjectName("textButton")
        self.clear_finished_btn.clicked.connect(self._clear_finished)
        queue_header.addWidget(self.clear_finished_btn)
        queue_layout.addLayout(queue_header)

        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queueList")
        self.queue_list.setMinimumHeight(160)
        self.queue_list.setAlternatingRowColors(False)
        self.queue_list.setAccessibleName("PDF file queue")
        queue_layout.addWidget(self.queue_list, 1)
        root.addWidget(queue_card, 1)

        # Progress panel
        self.progress_panel = ProgressPanel()
        self.progress_panel.cancel_requested.connect(self._cancel)
        root.addWidget(self.progress_panel)

        # Main controls card: common options only.
        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls = QGridLayout(controls_card)
        controls.setContentsMargins(16, 14, 16, 14)
        controls.setHorizontalSpacing(12)
        controls.setVerticalSpacing(8)

        lang_label = QLabel("OCR language")
        lang_label.setObjectName("mutedLabel")
        controls.addWidget(lang_label, 0, 0)
        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(190)
        self.lang_combo.setAccessibleName("OCR language")
        self.lang_combo.setToolTip(
            "Auto detect checks every page in short PDFs and representative pages in long PDFs."
        )
        language_row = QHBoxLayout()
        language_row.setSpacing(6)
        language_row.addWidget(self.lang_combo, 1)
        self.language_picker_btn = QPushButton("Choose…")
        self.language_picker_btn.setObjectName("quietButton")
        self.language_picker_btn.setAccessibleName("Choose multiple OCR languages")
        self.language_picker_btn.setToolTip("Select any combination from the complete Tesseract catalogue.")
        self.language_picker_btn.clicked.connect(self._open_language_picker)
        language_row.addWidget(self.language_picker_btn)
        controls.addLayout(language_row, 1, 0)

        preset_label = QLabel("Preset")
        preset_label.setObjectName("mutedLabel")
        controls.addWidget(preset_label, 0, 1)
        self.preset_combo = QComboBox()
        for key, label in PRESET_LABELS.items():
            self.preset_combo.addItem(label, key)
        self.preset_combo.setToolTip(
            "Quick: fastest, no rotation or straightening.\n"
            "Standard: auto-rotate + fix tilted pages (default).\n"
            "Difficult Scan: higher image quality for poor scans."
        )
        self.preset_combo.setAccessibleName("OCR preset")
        controls.addWidget(self.preset_combo, 1, 1)

        checks = QVBoxLayout()
        checks.setSpacing(0)
        self.rotate_check = QCheckBox("Auto rotate")
        self.rotate_check.setToolTip("Detects pages scanned upside down or sideways and rotates them.")
        self.deskew_check = QCheckBox("Fix tilted pages")
        self.deskew_check.setToolTip("Straightens pages that were scanned slightly crooked.")
        checks.addWidget(self.rotate_check)
        checks.addWidget(self.deskew_check)
        controls.addLayout(checks, 0, 2, 2, 1)

        controls.setColumnStretch(3, 1)

        self.advanced_btn = QPushButton("Advanced settings")
        self.advanced_btn.setObjectName("textButton")
        self.advanced_btn.clicked.connect(self._open_settings)
        controls.addWidget(self.advanced_btn, 0, 4, 1, 1, Qt.AlignmentFlag.AlignRight)

        self.start_btn = QPushButton("Start OCR")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._start)
        controls.addWidget(self.start_btn, 1, 4)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        controls.addWidget(self.cancel_btn, 1, 5)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("quietButton")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        controls.addWidget(self.pause_btn, 1, 6)

        root.addWidget(controls_card)

        self.setCentralWidget(central)

        # Log panel as bottom dock
        from PySide6.QtWidgets import QDockWidget

        self.log_dock = QDockWidget("Detailed log", self)
        self.log_panel = LogPanel()
        self.log_dock.setWidget(self.log_panel)
        self.log_dock.hide()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

        self._populate_languages()
        self._populate_presets()

    def _populate_languages(self) -> None:
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        statuses = self.tesseract.statuses()
        choices: list[tuple[str, str]] = []
        choices.append((LANGUAGE_LABELS["auto"], "auto"))
        choices.extend(
            [
                (LANGUAGE_LABELS["chi_sim+vie"], "chi_sim+vie"),
                (LANGUAGE_LABELS["vie+eng"], "vie+eng"),
                (LANGUAGE_LABELS["vie"], "vie"),
                (LANGUAGE_LABELS["eng"], "eng"),
                (self._custom_language_label(), "custom"),
            ]
        )
        preset_codes = {"vie+eng", "vie", "eng"}
        models = self.tesseract.catalog_models()
        preferred = {code: index for index, code in enumerate(("vie", "eng", "chi_sim", "chi_tra", "jpn", "kor"))}
        models = sorted(models, key=lambda model: (preferred.get(model.code, 100), model.name.casefold()))
        for model in models:
            if model.code in preset_codes:
                continue
            choices.append((f"{model.name} ({model.code})  ·  {statuses.get(model.code, 'Available')}", model.code))
        for label, key in choices:
            self.lang_combo.addItem(label, key)

        idx = self.lang_combo.findData(self.settings.language_preset)
        if idx < 0 or not self.lang_combo.itemData(idx):
            for fallback in ("auto", "vie+eng", "vie", "eng"):
                idx = self.lang_combo.findData(fallback)
                if idx >= 0:
                    break
        self.lang_combo.setCurrentIndex(max(idx, 0))
        self.lang_combo.blockSignals(False)
        if not getattr(self, "_language_signal_connected", False):
            self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
            self._language_signal_connected = True

    def _custom_language_label(self) -> str:
        codes = list(dict.fromkeys(self.settings.custom_languages))
        if not codes:
            return LANGUAGE_LABELS["custom"]
        names = []
        for code in codes[:3]:
            model = self.tesseract.catalog_model(code)
            names.append(model.name if model is not None else code)
        suffix = ", ".join(names)
        if len(codes) > 3:
            suffix += f" +{len(codes) - 3}"
        return f"Multiple — {suffix}"

    def _populate_presets(self) -> None:
        idx = self.preset_combo.findData(self.settings.preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self._ui_preset = None
        self._apply_preset_to_checks()
        self.preset_combo.currentIndexChanged.connect(self._apply_preset_to_checks)

    def _apply_preset_to_checks(self) -> None:
        preset = self.preset_combo.currentData() or OcrPreset.STANDARD.value
        if preset == OcrPreset.QUICK.value:
            self.rotate_check.setChecked(False)
            self.deskew_check.setChecked(False)
            self.rotate_check.setEnabled(False)
            self.deskew_check.setEnabled(False)
        elif preset == OcrPreset.DIFFICULT.value:
            self.rotate_check.setChecked(True)
            self.deskew_check.setChecked(True)
            self.rotate_check.setEnabled(False)
            self.deskew_check.setEnabled(False)
        else:
            if self._ui_preset is not None and self._ui_preset != preset:
                self.rotate_check.setChecked(True)
                self.deskew_check.setChecked(True)
            elif self._ui_preset is None:
                self.rotate_check.setChecked(self.settings.rotate_pages)
                self.deskew_check.setChecked(self.settings.deskew)
            self.rotate_check.setEnabled(True)
            self.deskew_check.setEnabled(True)
        self._ui_preset = preset

    def _load_window_state(self) -> None:
        geometry = self.store.window_geometry()
        if geometry:
            self.restoreGeometry(geometry)

    # ------------------------------------------------------------- lifecycle

    def _after_start(self) -> None:
        self._run_dependency_check(first_run=self.store and not self.store.first_run_done())

    def _run_dependency_check(self, first_run: bool = False) -> None:
        self.statusBar().showMessage("Checking OCR components...")
        report = dependency_checker.check_dependencies()
        if first_run:
            self.store.set_first_run_done(True)
            dialog = FirstRunDialog(report, self)
            dialog.exec()
        missing = report.missing_names
        if missing:
            self.statusBar().showMessage("Missing: " + ", ".join(missing), 10000)
        elif report.languages_error:
            self.statusBar().showMessage("Warning: " + report.languages_error, 10000)
        else:
            self.statusBar().showMessage(
                f"Ready - OCRmyPDF {report.ocrmypdf.version}, Tesseract {report.tesseract.version}",
                8000,
            )
        self.tesseract.refresh()
        self._populate_languages()

    # ------------------------------------------------------------- drag & drop

    def _on_files_dropped(self, paths: list[Path]) -> None:
        pdfs: list[Path] = []
        folders: list[Path] = []
        for path in paths:
            if path.is_dir():
                folders.append(path)
            elif path.is_file() and path.suffix.lower() == ".pdf":
                pdfs.append(path)
            elif path.is_file():
                QMessageBox.information(self, "Not a PDF", f"Skipped (not a PDF):\n{path.name}")

        if folders:
            found = []
            for folder in folders:
                found.extend(sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"))
            if not found:
                QMessageBox.information(self, "No PDFs", f"No PDF files found in:\n{', '.join(str(f) for f in folders)}")
            else:
                answer = QMessageBox.question(
                    self,
                    "Add folder?",
                    f"Found {len(found)} PDF file(s) in the dropped folder(s).\n\nAdd them all to the queue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    pdfs.extend(found)

        if pdfs:
            self._add_jobs(pdfs)

    def _add_jobs(self, pdfs: list[Path]) -> None:
        jobs: list[Job] = []
        snapshot = self._snapshot_settings()
        reserved_outputs = [job.output_path for job in self.queue.jobs() if job.output_path]
        for pdf in pdfs:
            info = inspect_pdf(pdf)
            if info.error and not info.pages:
                QMessageBox.warning(self, "Cannot read PDF", f"{pdf.name}\n\n{info.error}")
                continue
            if info.encrypted:
                QMessageBox.warning(self, "Encrypted PDF", f"{pdf.name}\n\nThis PDF is password-protected. Remove the password first.")
                continue

            output = resolve_output_path(pdf, self.settings, reserved_paths=reserved_outputs)
            pages, valid_selection = self._resolve_pages(info.pages)
            if not valid_selection:
                continue
            reserved_outputs.append(str(output))
            job = Job(
                input_path=str(pdf),
                output_path=str(output),
                settings_json=snapshot,
                pages=pages,
                page_count=info.pages,
                file_size=info.size_bytes,
                has_text=info.has_text,
            )
            jobs.append(job)

        if jobs:
            self.queue.enqueue(jobs)
            self._refresh_queue()

    def _snapshot_settings(self) -> str:
        """Persist current UI state into settings and serialize a snapshot."""
        self.settings.rotate_pages = self.rotate_check.isChecked()
        self.settings.deskew = self.deskew_check.isChecked()
        self.settings.preset = self.preset_combo.currentData() or OcrPreset.STANDARD.value
        selected_language = self.lang_combo.currentData()
        if selected_language:
            self.settings.language_preset = selected_language
        self.settings.custom_languages = list(self.settings.custom_languages)
        return self.settings.to_json()

    def _apply_current_settings_to_waiting(self, waiting: list[Job], snapshot: str) -> bool:
        """Apply the controls as they look when Start OCR is pressed.

        Jobs used to keep the settings from the moment the PDF was added.
        Selecting Chinese + Vietnamese afterwards therefore had no effect and
        arbitrary catalogue codes were decoded back to Auto detect.
        """
        try:
            selected_settings = AppSettings.from_dict(json.loads(snapshot))
        except (json.JSONDecodeError, TypeError):
            selected_settings = self.settings
        waiting_ids = {job.id for job in waiting}
        reserved_outputs = [
            job.output_path
            for job in self.queue.jobs()
            if job.id not in waiting_ids and job.output_path
        ]
        for job in waiting:
            pages, valid = self._resolve_pages(job.page_count, self.settings)
            if not valid:
                return False
            job.pages = pages
            job_settings = effective_settings_for_document(selected_settings, job.has_text)
            job.settings_json = job_settings.to_json()
            job.output_path = str(
                resolve_output_path(job.input, self.settings, reserved_paths=reserved_outputs)
            )
            reserved_outputs.append(job.output_path)
            self.queue.job_updated.emit(job)
        return True

    def _resolve_pages(
        self,
        page_count: int,
        settings: AppSettings | None = None,
    ) -> tuple[list[int] | None, bool]:
        """Apply page range / exclude settings.

        Returns ``(pages, valid)``. ``None`` means all pages and an empty list
        is a valid selection that excludes every page.
        """
        s = settings or self.settings
        pages: list[int] | None = None
        if s.page_selection_mode == "range" and not s.page_range.strip():
            QMessageBox.warning(self, "Invalid page selection", "Choose at least one page or switch Pages back to All pages.")
            return None, False
        if s.page_selection_mode == "range" and s.page_range.strip():
            err = validate_spec(s.page_range, page_count)
            if err:
                QMessageBox.warning(self, "Invalid page selection", f"{err}\nPages in this file: 1-{page_count}")
                return None, False
            pages = parse_spec_to_pages(s.page_range, page_count)
        if s.exclude_pages.strip():
            excluded = parse_spec_to_pages(s.exclude_pages, page_count)
            if excluded is None:
                QMessageBox.warning(self, "Invalid pages to exclude", f"Check the format. Pages in this file: 1-{page_count}")
                return None, False
            base = set(pages if pages is not None else range(1, page_count + 1))
            pages = sorted(base.difference(excluded))
        return pages, True

    # --------------------------------------------------------------- actions

    def _start(self) -> None:
        report = dependency_checker.check_dependencies()
        if not report.ocrmypdf.present or not report.tesseract.present:
            QMessageBox.warning(
                self,
                "OCR components missing",
                "A required OCR component is missing.\n\n"
                + "\n".join(
                    f"{component.name}: {component.error or 'not found'}"
                    for component in (report.ocrmypdf, report.tesseract)
                    if not component.present
                ),
            )
            return
        if self.settings.output_type == "pdfa" and not report.ghostscript.present:
            QMessageBox.warning(
                self,
                "Ghostscript required",
                "PDF/A output needs Ghostscript, but it was not found.\n\n"
                "Install Ghostscript, or choose Auto/PDF in Advanced settings.",
            )
            return

        snapshot = self._snapshot_settings()

        waiting = [j for j in self.queue.jobs() if j.status == JobStatus.WAITING]
        if not waiting:
            QMessageBox.information(self, "Nothing to do", "Add PDF files to the queue first.")
            return
        if not self._apply_current_settings_to_waiting(waiting, snapshot):
            return
        self.queue.set_concurrency(self.settings.concurrent_files)
        self.store.save(self.settings)
        self._begin_language_preflight(waiting)

    def _cancel(self) -> None:
        if self._preparing_languages:
            if self._language_worker is not None and hasattr(self._language_worker, "cancel"):
                self._language_worker.cancel()
            self._abort_language_preflight("Language preparation cancelled.")
            return
        self.queue.cancel_current()
        self.cancel_btn.setEnabled(False)
        self.progress_panel.finish("Cancelling...")

    def _toggle_pause(self) -> None:
        if self.queue.is_paused():
            self.queue.resume_queue()
        else:
            self.queue.pause_queue()

    def _open_settings(self) -> None:
        self._snapshot_settings()
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.result_settings()
            self.queue.set_concurrency(self.settings.concurrent_files)
            self.store.save(self.settings)
            self._populate_languages()

    def _open_history(self) -> None:
        dialog = HistoryDialog(self.history, self)
        dialog.run_again.connect(self._run_again)
        dialog.exec()

    def _run_again(self, entry) -> None:
        pdf = Path(entry.input)
        if not pdf.exists():
            QMessageBox.warning(self, "File not found", f"The input file no longer exists:\n{pdf}")
            return
        info = inspect_pdf(pdf)
        snapshot = entry.settings_json or self.settings.to_json()
        try:
            saved = AppSettings.from_dict(json.loads(snapshot))
        except (json.JSONDecodeError, TypeError):
            saved = self.settings
        pages = None
        if not info.error:
            pages, valid_selection = self._resolve_pages(info.pages, saved)
            if not valid_selection:
                return
        job = Job(
            input_path=str(pdf),
            output_path=str(resolve_output_path(pdf, saved)),
            settings_json=json.dumps(saved.to_dict(), ensure_ascii=False),
            pages=pages,
            page_count=info.pages,
            file_size=info.size_bytes,
            has_text=info.has_text,
        )
        self.queue.enqueue([job])
        self._refresh_queue()

    def _toggle_log(self) -> None:
        self.log_dock.setVisible(self.log_btn.isChecked())

    def _open_output_folder(self, job: Job) -> None:
        if job.output_path and Path(job.output_path).exists():
            folder = str(Path(job.output_path).parent)
            subprocess.Popen(["explorer", long_path(folder)])
        else:
            subprocess.Popen(["explorer", long_path(job.input.parent)])

    def _open_output(self, job: Job) -> None:
        if job.output_path and Path(job.output_path).exists():
            os.startfile(job.output_path)  # noqa: S606
        else:
            QMessageBox.warning(self, "Output not found", f"The output file does not exist:\n{job.output_path}")

    # ---------------------------------------------------------------- signals

    def _on_job_updated(self, job: Job) -> None:
        if job.status in (JobStatus.PREPARING, JobStatus.PROCESSING):
            self.progress_panel.start_job(job.input.name, job.progress_total or job.page_count or 1)
            self.progress_panel.update_stage(job.stage)
            self.progress_panel.update_progress(job.progress_current, job.progress_total)
            self.cancel_btn.setEnabled(True)
        elif job.status == JobStatus.WAITING and not self.queue.is_running():
            self.progress_panel.finish()
        self._refresh_queue()

    def _on_job_finished(self, job: Job) -> None:
        job.started_at = ""
        if job.status == JobStatus.COMPLETED:
            self.progress_panel.finish("Completed")
        elif job.status == JobStatus.CANCELLED:
            self.progress_panel.finish("Cancelled")
        elif job.status == JobStatus.SKIPPED:
            self.progress_panel.finish("Skipped")
        else:
            self.progress_panel.finish(job.error_message or "Failed")
        try:
            self.history.add(self.history.from_job(job))
        except Exception as exc:  # noqa: BLE001 - history must never break OCR
            log.warning("Could not save history: %s", exc)
        if job.status == JobStatus.FAILED and job.error_message:
            # Keep completion non-blocking: the queue row carries the cause,
            # while the status bar points to the recovery action.
            self.statusBar().showMessage(
                f"OCR failed for {job.input.name}. Select Retry or open the log.",
                12000,
            )

    def _on_queue_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"{done} / {total} files finished", 5000)

    def _on_worker_log(self, level: str, message: str) -> None:
        self.log_panel.append_line(level, message)

    def _on_status_changed(self, running: bool, paused: bool) -> None:
        self.start_btn.setEnabled(not running and not paused)
        self.cancel_btn.setEnabled(running)
        self.pause_btn.setEnabled(running)
        self.pause_btn.setText("Resume" if paused else "Pause")
        if not running:
            self.cancel_btn.setEnabled(False)
            self.progress_panel.finish()

    def _clear_finished(self) -> None:
        self.queue.clear_finished()
        self._refresh_queue()

    def _on_language_changed(self) -> None:
        key = self.lang_combo.currentData()
        if not key:
            return
        if key != "custom":
            self.settings.language_preset = key
            return
        self._open_language_picker()

    def _open_language_picker(self) -> None:
        previous_key = self.settings.language_preset
        dialog = LanguagePickerDialog(self.tesseract, self.settings.custom_languages, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selected_codes()
            if not selected:
                QMessageBox.information(self, "Choose a language", "Select at least one OCR language model.")
            else:
                self.settings.custom_languages = selected
                self.settings.language_preset = "custom"
                self._populate_languages()
                return
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(previous_key)))
        self.lang_combo.blockSignals(False)

    # ------------------------------------------------------- language setup

    def _begin_language_preflight(self, waiting: list[Job]) -> None:
        """Detect and/or download models before starting the OCR queue."""
        if self._preparing_languages:
            return
        self._language_generation += 1
        generation = self._language_generation
        self._preflight_waiting = list(waiting)
        self._resolved_languages = {}
        self.queue.begin_preparation(self._preflight_waiting)
        detection_jobs: list[tuple[str, Path, list[int] | None]] = []
        manual_codes: set[str] = set()
        for job in waiting:
            settings = self._settings_for_job(job)
            if settings.language_preset == "auto":
                if job.pages == []:
                    continue
                detection_jobs.append((job.id, Path(job.input_path), job.pages))
            else:
                codes = settings.custom_languages if settings.language_preset == "custom" else settings.language_preset.split("+")
                manual_codes.update(code for code in codes if code)

        self._set_language_preparing(True, "Detecting languages locally…" if detection_jobs else "Preparing language models…")
        if detection_jobs:
            service = LanguageDetectionService(self.tesseract)
            self._start_language_worker(
                LanguageDetectionWorker(detection_jobs, service),
                lambda results, current_generation=generation: self._on_detection_finished(
                    current_generation,
                    results,
                ),
                generation,
            )
        else:
            self._begin_language_download(manual_codes, generation)

    def _start_language_worker(self, worker, finished_handler, generation: int) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished_handler)
        worker.finished.connect(thread.quit)
        worker.failed.connect(
            lambda message, current_generation=generation: self._on_language_failed(
                current_generation,
                message,
            )
        )
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(
            lambda current_generation=generation: self._on_language_cancelled(current_generation)
        )
        worker.cancelled.connect(thread.quit)
        if isinstance(worker, LanguageDownloadWorker):
            worker.progress.connect(
                lambda code, current, total, current_generation=generation: self._on_download_progress(
                    current_generation,
                    code,
                    current,
                    total,
                )
            )
        else:
            worker.progress.connect(
                lambda job_id, current, total, message, current_generation=generation: self._on_detection_progress(
                    current_generation,
                    job_id,
                    current,
                    total,
                    message,
                )
            )
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current_thread=thread: self._on_language_thread_finished(current_thread))
        self._language_thread = thread
        self._language_worker = worker
        thread.start()

    def _on_language_thread_finished(self, thread: QThread) -> None:
        if self._language_thread is thread:
            self._language_worker = None
            self._language_thread = None

    def _on_detection_progress(
        self,
        generation: int,
        job_id: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        job = next((candidate for candidate in self._preflight_waiting if candidate.id == job_id), None)
        if job is not None:
            self.queue.update_preparation(job, message, current, total)
        self.statusBar().showMessage(f"{message} ({current}/{total})")

    def _on_detection_finished(self, generation: int, results: dict[str, DocumentDetection]) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        self._detected_results = results
        manual_codes: set[str] = set()
        try:
            for job in self._preflight_waiting:
                settings = self._settings_for_job(job)
                if settings.language_preset != "auto":
                    codes = settings.custom_languages if settings.language_preset == "custom" else settings.language_preset.split("+")
                    manual_codes.update(code for code in codes if code)
                    continue
                detection = results.get(job.id)
                if detection is None:
                    raise RuntimeError(f"No detection result was returned for {Path(job.input_path).name}.")
                codes = list(detection.languages)
                if detection.needs_review:
                    dialog = LanguageReviewDialog(Path(job.input_path).name, detection, self.tesseract, self)
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        self._abort_language_preflight("Language selection cancelled.", generation)
                        return
                    codes = dialog.selected_codes()
                if not codes:
                    raise RuntimeError(f"No language was detected for {Path(job.input_path).name}.")
                self._resolved_languages[job.id] = list(dict.fromkeys(codes))
                manual_codes.update(codes)
        except Exception as exc:  # noqa: BLE001 - keep the queue idle on preflight errors
            self._on_language_failed(generation, str(exc))
            return
        self._begin_language_download(manual_codes, generation)

    def _begin_language_download(self, codes: set[str], generation: int) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        codes = {str(code).strip() for code in codes if str(code).strip()}
        try:
            missing = [code for code in sorted(codes) if self.tesseract.status(code) == "Available"]
        except Exception as exc:  # noqa: BLE001 - invalid legacy settings must be recoverable
            self._on_language_failed(generation, f"Unknown OCR language selection: {exc}")
            return
        self._download_codes = list(codes)
        if missing:
            no_download = [
                job for job in self._preflight_waiting
                if not self._settings_for_job(job).auto_download_languages
            ]
            if no_download:
                self._on_language_failed(
                    generation,
                    "Missing language model(s): " + ", ".join(missing) + ". Enable automatic downloads in Advanced Settings."
                )
                return
            self._set_language_preparing(True, f"Downloading {len(missing)} language model(s)…")
            self._start_language_worker(
                LanguageDownloadWorker(self.tesseract, missing),
                lambda paths, current_generation=generation: self._on_download_finished(
                    current_generation,
                    paths,
                ),
                generation,
            )
            return
        self._finish_language_preflight(generation)

    def _on_download_progress(self, generation: int, code: str, current: int, total: int) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        for job in self._preflight_waiting:
            self.queue.update_preparation(job, f"Downloading {code}", current, total)
        if total:
            self.statusBar().showMessage(f"Downloading {code}: {current / total:.0%}")
        else:
            self.statusBar().showMessage(f"Downloading {code}…")

    def _on_download_finished(self, generation: int, _paths) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        self.tesseract.refresh()
        self._finish_language_preflight(generation)

    def _finish_language_preflight(self, generation: int) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        for job in self._preflight_waiting:
            codes = self._resolved_languages.get(job.id)
            if not codes:
                continue
            settings = self._settings_for_job(job)
            settings.language_preset = "custom"
            settings.custom_languages = codes
            job.settings_json = json.dumps(settings.to_dict(), ensure_ascii=False)
        prepared_jobs = list(self._preflight_waiting)
        self.queue.finish_preparation(prepared_jobs)
        self._set_language_preparing(False, "Language models ready.")
        self.store.save(self.settings)
        self._preflight_waiting = []
        self._resolved_languages = {}
        self.queue.start()

    def _set_language_preparing(self, preparing: bool, message: str = "") -> None:
        self._preparing_languages = preparing
        for widget in (
            self.start_btn,
            self.advanced_btn,
            self.lang_combo,
            self.language_picker_btn,
            self.preset_combo,
        ):
            widget.setEnabled(not preparing)
        self.cancel_btn.setEnabled(preparing)
        if message:
            self.statusBar().showMessage(message)

    def _abort_language_preflight(self, message: str, generation: int | None = None) -> None:
        if generation is not None and generation != self._language_generation:
            return
        jobs = list(self._preflight_waiting)
        self._language_generation += 1
        self.queue.finish_preparation(jobs)
        self._set_language_preparing(False, message)
        self._preflight_waiting = []
        self._resolved_languages = {}

    def _on_language_cancelled(self, generation: int) -> None:
        self._abort_language_preflight("Language preparation cancelled.", generation)

    def _on_language_failed(self, generation: int, message: str) -> None:
        if generation != self._language_generation or not self._preparing_languages:
            return
        failed_jobs = list(self._preflight_waiting)
        self._language_generation += 1
        self._set_language_preparing(False)
        self.queue.fail_preparation(failed_jobs, message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Language preparation failed")
        box.setText(message)
        box.setInformativeText(
            "OCR has not started. Check your network connection, or download the "
            "matching .traineddata file manually into the app tessdata cache and retry."
        )
        retry = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is retry:
            for job in failed_jobs:
                self.queue.retry(job)
            QTimer.singleShot(0, lambda jobs=failed_jobs: self._begin_language_preflight(jobs))
        else:
            self._preflight_waiting = []
            self._resolved_languages = {}

    def _settings_for_job(self, job: Job) -> AppSettings:
        try:
            return AppSettings.from_dict(json.loads(job.settings_json))
        except (json.JSONDecodeError, TypeError, ValueError):
            return AppSettings.from_dict(self.settings.to_dict())

    def _refresh_queue(self) -> None:
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        jobs = self.queue.jobs()
        self.queue_count_label.setText(f"{len(jobs)} file" + ("" if len(jobs) == 1 else "s"))
        self.clear_finished_btn.setEnabled(any(job.is_terminal for job in jobs))
        if not jobs:
            placeholder = QLabel("No PDFs in the queue yet. Drop a file above to begin.")
            placeholder.setObjectName("mutedLabel")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setMinimumHeight(96)
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(placeholder.sizeHint())
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, placeholder)
        for job in jobs:
            widget = JobWidget(job)
            widget.remove_requested.connect(self._on_remove_job)
            widget.retry_requested.connect(lambda j=job: self.queue.retry(j))
            widget.view_log_requested.connect(self._view_job_log)
            widget.open_output_requested.connect(self._open_output)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, widget)
        self.queue_list.blockSignals(False)

    def _on_remove_job(self, job: Job) -> None:
        self.queue.remove_job(job)
        self._refresh_queue()

    def _view_job_log(self, job: Job) -> None:
        self._toggle_log()
        if job.error_detail:
            self.log_panel.view.appendPlainText(job.error_detail)

    def _tick(self) -> None:
        if self.queue.is_running() or self._preparing_languages:
            self.progress_panel.update_eta()
            running = [j for j in self.queue.jobs() if j.status == JobStatus.PROCESSING]
            for job in running:
                if not job.started_at:
                    job.started_at = str(time.time())

    # ------------------------------------------------------------------ close

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.queue.has_pending():
            answer = QMessageBox.question(
                self,
                "Quit while processing?",
                "OCR is still running. Quit anyway?\n\nRunning jobs will be cancelled.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self._language_worker is not None and hasattr(self._language_worker, "cancel"):
            self._language_worker.cancel()
        self._eta_timer.stop()
        self.queue.stop_all()
        self.store.save(self.settings)
        self.store.set_window_geometry(self.saveGeometry())
        event.accept()
