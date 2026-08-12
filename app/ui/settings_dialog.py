"""Advanced settings dialog: OCR mode, pages, timeout, output, performance."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from app.core.page_ranges import validate_spec
from app.models.settings import (
    AppSettings,
    OcrMode,
    Optimization,
    OutputType,
    PageSelectionMode,
)

TIMEOUT_CHOICES = [
    ("30 seconds", 30),
    ("60 seconds", 60),
    ("120 seconds", 120),
    ("180 seconds (default)", 180),
    ("300 seconds", 300),
    ("Unlimited / advanced", 0),
]

JOBS_CHOICES = [
    ("Auto", 0),
    ("1 worker", 1),
    ("2 workers", 2),
    ("4 workers", 4),
    ("8 workers", 8),
]


class SettingsDialog(QDialog):
    """Edit advanced OCR settings. Returns the modified AppSettings on accept."""

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced Settings")
        self.setSizeGripEnabled(True)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        max_width = max(480, (available.width() - 80) if available is not None else 640)
        max_height = max(420, (available.height() - 80) if available is not None else 720)
        self.setMinimumSize(min(480, max_width), min(420, max_height))
        self.resize(min(640, max_width), min(720, max_height))
        # Edit a copy so Cancel never changes the live application state.
        self._settings = AppSettings.from_dict(settings.to_dict())

        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 4, 12, 8)
        root.setSpacing(10)

        # --- OCR behavior
        ocr_box = QGroupBox("OCR behavior")
        form = QFormLayout(ocr_box)

        self.mode_combo = QComboBox()
        for mode in (OcrMode.SKIP, OcrMode.REDO, OcrMode.FORCE):
            self.mode_combo.addItem(mode.value, mode.value)
        self.mode_combo.setToolTip(
            "Skip existing text: OCR only pages that have no text yet (fastest).\n"
            "Redo OCR: replace the old text layer.\n"
            "Force OCR: rasterize pages and OCR them again."
        )
        form.addRow("OCR Mode:", self.mode_combo)

        self.timeout_combo = QComboBox()
        for label, value in TIMEOUT_CHOICES:
            self.timeout_combo.addItem(label, value)
        self.timeout_combo.setToolTip(
            "Maximum time OCRmyPDF spends on one page.\n"
            "Pages that exceed the limit are skipped and keep the original content."
        )
        form.addRow("Max time per page:", self.timeout_combo)

        self.sidecar_check = QCheckBox("Also export recognized text (.txt)")
        self.sidecar_check.setToolTip("Saves a plain-text file next to the output PDF.")
        form.addRow("", self.sidecar_check)

        self.auto_download_check = QCheckBox("Download missing language packs automatically")
        self.auto_download_check.setToolTip(
            "Downloads official tessdata_fast models into your user app data folder "
            "when OCR starts. No Administrator permission is required."
        )
        form.addRow("", self.auto_download_check)

        root.addWidget(ocr_box)

        # --- Pages
        pages_box = QGroupBox("Pages")
        pages_form = QFormLayout(pages_box)

        self.page_mode_combo = QComboBox()
        self.page_mode_combo.addItem("All pages", PageSelectionMode.ALL.value)
        self.page_mode_combo.addItem("Selected pages", PageSelectionMode.RANGE.value)
        pages_form.addRow("Pages:", self.page_mode_combo)

        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("e.g. 1-50,52-100  or  3-end")
        self.range_edit.setToolTip("Examples: 1-50,52-100  •  3-end  •  2,5,9")
        pages_form.addRow("Page selection:", self.range_edit)

        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText("e.g. 51,124")
        self.exclude_edit.setToolTip(
            "Pages to skip, e.g. blank or broken scans.\n"
            "App converts this automatically: file of 200 pages with '51' -> 1-50,52-end"
        )
        pages_form.addRow("Pages to exclude:", self.exclude_edit)

        root.addWidget(pages_box)

        # --- Output
        out_box = QGroupBox("Output")
        out_form = QFormLayout(out_box)

        self.folder_combo = QComboBox()
        self.folder_combo.addItem("Same folder as input", "same")
        self.folder_combo.addItem("Custom folder", "custom")
        out_form.addRow("Output folder:", self.folder_combo)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_btn)
        out_form.addRow("", folder_row)

        self.output_type_combo = QComboBox()
        for label, value in (
            ("Auto", OutputType.AUTO.value),
            ("PDF", OutputType.PDF.value),
            ("PDF/A (archive)", OutputType.PDFA.value),
        ):
            self.output_type_combo.addItem(label, value)
        self.output_type_combo.setToolTip(
            "PDF/A is a long-term archive format. Auto lets OCRmyPDF decide."
        )
        out_form.addRow("Output format:", self.output_type_combo)

        self.optimize_combo = QComboBox()
        for label, value in (
            ("None", Optimization.NONE.value),
            ("Standard", Optimization.STANDARD.value),
            ("High", Optimization.HIGH.value),
            ("Maximum", Optimization.MAXIMUM.value),
        ):
            self.optimize_combo.addItem(label, value)
        self.optimize_combo.setToolTip(
            "How aggressively the output PDF is compressed.\n"
            "Maximum produces smaller files but takes much longer."
        )
        out_form.addRow("PDF optimization:", self.optimize_combo)

        root.addWidget(out_box)

        # --- Performance
        perf_box = QGroupBox("Performance")
        perf_form = QFormLayout(perf_box)

        self.jobs_combo = QComboBox()
        for label, value in JOBS_CHOICES:
            self.jobs_combo.addItem(label, value)
        self.jobs_combo.setToolTip("Number of parallel OCR worker processes (per file).")
        perf_form.addRow("CPU workers:", self.jobs_combo)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 4)
        self.concurrent_spin.setToolTip(
            "How many PDFs to process at the same time.\n"
            "1 is recommended; more uses much more RAM and CPU."
        )
        perf_form.addRow("Concurrent files:", self.concurrent_spin)

        root.addWidget(perf_box)

        # --- Buttons
        scroll.setWidget(content)
        dialog_layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.setObjectName("settingsFooter")
        self.cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert self.cancel_btn is not None
        assert self.ok_btn is not None
        self.cancel_btn.setText("Cancel")
        self.ok_btn.setText("OK")
        self.ok_btn.setObjectName("primaryButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        dialog_layout.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        s = self._settings
        idx = self.mode_combo.findData(s.ocr_mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

        timeout = s.tesseract_timeout
        if timeout == 0:
            timeout = 0
        idx = self.timeout_combo.findData(timeout if timeout in {0, 30, 60, 120, 180, 300} else 180)
        if idx >= 0:
            self.timeout_combo.setCurrentIndex(idx)

        self.sidecar_check.setChecked(s.sidecar)
        self.auto_download_check.setChecked(s.auto_download_languages)
        idx = self.page_mode_combo.findData(s.page_selection_mode)
        if idx >= 0:
            self.page_mode_combo.setCurrentIndex(idx)
        self.range_edit.setText(s.page_range)
        self.exclude_edit.setText(s.exclude_pages)

        idx = self.folder_combo.findData(s.output_folder_mode)
        if idx >= 0:
            self.folder_combo.setCurrentIndex(idx)
        self.folder_edit.setText(s.output_folder)

        idx = self.output_type_combo.findData(s.output_type)
        if idx >= 0:
            self.output_type_combo.setCurrentIndex(idx)
        idx = self.optimize_combo.findData(s.optimize)
        if idx >= 0:
            self.optimize_combo.setCurrentIndex(idx)
        idx = self.jobs_combo.findData(s.jobs)
        if idx >= 0:
            self.jobs_combo.setCurrentIndex(idx)
        self.concurrent_spin.setValue(s.concurrent_files)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)
            self.folder_combo.setCurrentIndex(self.folder_combo.findData("custom"))

    def _on_accept(self) -> None:
        s = self._settings
        s.ocr_mode = self.mode_combo.currentData()
        s.tesseract_timeout = self.timeout_combo.currentData()
        s.sidecar = self.sidecar_check.isChecked()
        s.auto_download_languages = self.auto_download_check.isChecked()

        s.page_selection_mode = self.page_mode_combo.currentData()
        page_range = self.range_edit.text().strip()
        exclude = self.exclude_edit.text().strip()
        if s.page_selection_mode == PageSelectionMode.RANGE.value and not page_range:
            QMessageBox.warning(self, "Invalid pages", "Enter a page range, or choose All pages.")
            return
        s.page_range = page_range
        s.exclude_pages = exclude

        error = self._validate_pages(page_range, exclude)
        if error:
            QMessageBox.warning(self, "Invalid pages", error)
            return

        s.output_folder_mode = self.folder_combo.currentData()
        s.output_folder = self.folder_edit.text().strip()
        s.output_type = self.output_type_combo.currentData()
        s.optimize = self.optimize_combo.currentData()
        s.jobs = self.jobs_combo.currentData()
        s.concurrent_files = self.concurrent_spin.value()
        self.accept()

    @staticmethod
    def _validate_pages(page_range: str, exclude: str) -> str | None:
        if page_range:
            err = validate_spec(page_range, 1 << 30)  # upper bound not yet known
            if err:
                return err + "\nExample: 1-50,52-100 or 3-end"
        if exclude:
            err = validate_spec(exclude, 1 << 30)
            if err:
                return err + "\nExample: 51,124"
        return None

    def result_settings(self) -> AppSettings:
        return self._settings
