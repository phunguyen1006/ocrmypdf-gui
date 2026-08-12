"""History dialog: recent jobs with actions."""
from __future__ import annotations

import datetime
import json
import os
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QMessageBox,
)

from app.services.history_service import HistoryEntry, HistoryService
from app.utils.paths import long_path


class HistoryDialog(QDialog):
    run_again = Signal(object)  # HistoryEntry

    def __init__(self, history: HistoryService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("History")
        self.setMinimumSize(760, 420)
        self._history = history
        self._entries: list[HistoryEntry] = []

        root = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Input", "Output", "Date", "Duration", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.open_out_btn = QPushButton("Open output")
        self.open_dir_btn = QPushButton("Open folder")
        self.run_again_btn = QPushButton("Run again")
        self.remove_btn = QPushButton("Remove from history")
        self.clear_btn = QPushButton("Clear all")
        self.close_btn = QPushButton("Close")
        self.close_btn.setDefault(True)

        self.open_out_btn.clicked.connect(lambda: self._selected(self._open_output))
        self.open_dir_btn.clicked.connect(lambda: self._selected(self._open_folder))
        self.run_again_btn.clicked.connect(lambda: self._selected(self._run_again))
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn.clicked.connect(self._clear_all)
        self.close_btn.clicked.connect(self.accept)

        buttons.addWidget(self.open_out_btn)
        buttons.addWidget(self.open_dir_btn)
        buttons.addWidget(self.run_again_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

        self.refresh()

    def refresh(self) -> None:
        self._entries = self._history.recent(200)
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(entry.input)))
            self.table.item(row, 0).setToolTip(entry.input)
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(entry.output) or ""))
            self.table.item(row, 1).setToolTip(entry.output)
            self.table.setItem(row, 2, QTableWidgetItem(
                datetime.datetime.fromtimestamp(entry.date).strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(row, 3, QTableWidgetItem(_duration_text(entry.duration_seconds)))
            self.table.setItem(row, 4, QTableWidgetItem(entry.status))

    def _selected(self, callback) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        for row in rows:
            callback(self._entries[row])

    def _open_output(self, entry: HistoryEntry) -> None:
        if entry.output and os.path.exists(entry.output):
            os.startfile(entry.output)  # noqa: S606 - Windows-only app

    def _open_folder(self, entry: HistoryEntry) -> None:
        path = os.path.dirname(entry.output) if entry.output else ""
        if not path or not os.path.isdir(path):
            path = os.path.dirname(entry.input) or "."
        subprocess.Popen(["explorer", long_path(path)])

    def _run_again(self, entry: HistoryEntry) -> None:
        self.run_again.emit(entry)
        self.accept()

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._history.remove(self._entries[row])
        self.refresh()

    def _clear_all(self) -> None:
        if QMessageBox.question(self, "Clear history", "Remove all history entries?") == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self.refresh()


def _duration_text(seconds: float) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h {m}m"
    return f"{m}m {s}s"
