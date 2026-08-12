"""Detailed log panel (dockable) with copy / save / clear actions."""
from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.paths import app_log_dir


class LogPanel(QWidget):
    """Time-stamped log lines from workers and the app itself."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("Detailed log"))
        header.addStretch()

        self.copy_btn = QPushButton("Copy log")
        self.save_btn = QPushButton("Save log...")
        self.clear_btn = QPushButton("Clear")
        for btn in (self.copy_btn, self.save_btn, self.clear_btn):
            btn.setFixedHeight(24)
            header.addWidget(btn)
        root.addLayout(header)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        root.addWidget(self.view, 1)

        self.copy_btn.clicked.connect(self.copy)
        self.save_btn.clicked.connect(self.save)
        self.clear_btn.clicked.connect(self.clear)

    def append_line(self, level: str, message: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {"warning": "WARN ", "error": "ERROR", "stderr": "WARN "}.get(level, "INFO")
        line = f"{ts} {prefix} {message}"
        self.view.appendPlainText(line)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def copy(self) -> None:
        self.view.selectAll()
        self.view.copy()
        cursor = self.view.textCursor()
        cursor.clearSelection()
        self.view.setTextCursor(cursor)

    def save(self) -> None:
        default = str(app_log_dir() / f"ocr-log-{datetime.date.today().isoformat()}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save log", default, "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.view.toPlainText())
        except OSError as exc:
            self.append_line("error", f"Could not save log: {exc}")

    def clear(self) -> None:
        self.view.clear()