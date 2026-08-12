"""Language catalogue picker and low-confidence detection confirmation."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.services.language_detection_service import DocumentDetection, REVIEW_CONFIDENCE_THRESHOLD
from app.services.tesseract_service import TesseractService


class LanguagePickerDialog(QDialog):
    """Searchable, status-aware picker for the complete language catalogue."""

    def __init__(
        self,
        service: TesseractService,
        selected_codes: Iterable[str] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._selected_codes = set(str(code) for code in selected_codes)
        self.setWindowTitle("Choose OCR languages")
        self.setMinimumSize(540, 520)
        self.resize(640, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("OCR language models")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        hint = QLabel("Models are listed locally. Missing models download only when OCR starts.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by language name or code…")
        self.search_edit.setAccessibleName("Search language catalogue")
        self.search_edit.textChanged.connect(self._refresh_list)
        root.addWidget(self.search_edit)

        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All", "all")
        self.filter_combo.addItem("Installed", "Installed")
        self.filter_combo.addItem("Cached", "Cached")
        self.filter_combo.addItem("Available", "Available")
        self.filter_combo.setAccessibleName("Language status filter")
        self.filter_combo.currentIndexChanged.connect(self._refresh_list)
        root.addWidget(self.filter_combo)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("languageList")
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setAccessibleName("OCR language models")
        self.list_widget.itemChanged.connect(self._remember_item)
        root.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._models = [(model, service.status(model.code)) for model in service.catalog_models()]
        self._refresh_list()

    def _refresh_list(self) -> None:
        query = self.search_edit.text().strip().casefold()
        status_filter = self.filter_combo.currentData()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for model, status in self._models:
            haystack = f"{model.name} {model.code}".casefold()
            if query and query not in haystack:
                continue
            if status_filter != "all" and status != status_filter:
                continue
            item = QListWidgetItem(f"{model.name}  ({model.code})  —  {status}")
            item.setData(Qt.ItemDataRole.UserRole, model.code)
            item.setToolTip(f"{model.name} · {model.code}\n{status}\n{model.remote_path}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if model.code in self._selected_codes else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _remember_item(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole)
        if not code:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_codes.add(str(code))
        else:
            self._selected_codes.discard(str(code))

    def selected_codes(self) -> list[str]:
        for index in range(self.list_widget.count()):
            self._remember_item(self.list_widget.item(index))
        return [model.code for model, _status in self._models if model.code in self._selected_codes]


class LanguageReviewDialog(QDialog):
    """Ask for confirmation when per-page detection is ambiguous."""

    def __init__(self, filename: str, detection: DocumentDetection, service: TesseractService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm detected languages")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(f"Confirm languages for {filename}")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        summary = QLabel(
            "Auto detect found a low-confidence result. Select every language present; "
            "the selected models will be downloaded before OCR if needed."
        )
        summary.setWordWrap(True)
        summary.setObjectName("mutedLabel")
        root.addWidget(summary)

        self.checks = []
        codes = list(dict.fromkeys(detection.candidates or detection.languages))
        for code in codes:
            model = service.catalog_model(code)
            if model is None:
                continue
            from PySide6.QtWidgets import QCheckBox

            check = QCheckBox(f"{model.name} ({code}) — {service.status(code)}")
            check.setChecked(code in detection.languages or len(codes) == 1)
            check.setProperty("languageCode", code)
            self.checks.append(check)
            root.addWidget(check)

        pages = ", ".join(
            str(result.page)
            for result in detection.page_results
            if result.candidates or result.confidence < REVIEW_CONFIDENCE_THRESHOLD
        )
        if pages:
            page_label = QLabel(f"Pages needing confirmation: {pages}")
            page_label.setObjectName("mutedLabel")
            root.addWidget(page_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept_if_selected)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept_if_selected(self) -> None:
        if self.selected_codes():
            self.accept()

    def selected_codes(self) -> list[str]:
        return [
            str(check.property("languageCode"))
            for check in self.checks
            if check.isChecked()
        ]
