"""Drag & drop zone for PDF files and folders."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout, QPushButton


class DropZone(QFrame):
    """A dashed-border area accepting PDF files / folders (or a click)."""

    files_dropped = Signal(list)  # list[Path]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(132)
        self.setObjectName("dropZone")
        self.setProperty("dragActive", False)
        self.setAccessibleName("PDF drop zone")
        self.setAccessibleDescription("Drop one or more PDF files here, or choose files from your computer.")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Drop PDF files here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: 700;")

        subtitle = QLabel("or")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #5f5f5f;")

        self.choose_button = QPushButton("Choose PDF files")
        self.choose_button.setObjectName("primaryButton")
        self.choose_button.setMinimumWidth(170)
        self.choose_button.setAccessibleName("Choose PDF files")
        self.choose_button.clicked.connect(self._choose_files)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.choose_button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose PDF files",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if paths:
            self.files_dropped.emit([Path(p) for p in paths])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self.files_dropped.emit(paths)
        self._set_drag_active(False)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
