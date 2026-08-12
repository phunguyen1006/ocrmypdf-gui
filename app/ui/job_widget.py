"""One row in the file queue: filename, pages, size, status, progress."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.job import Job, JobStatus

_STATUS_COLORS = {
    JobStatus.WAITING: "#8a8a8a",
    JobStatus.PROCESSING: "#111111",
    JobStatus.COMPLETED: "#111111",
    JobStatus.FAILED: "#9f1d1d",
    JobStatus.CANCELLED: "#5f5f5f",
    JobStatus.SKIPPED: "#8a8a8a",
}


class JobWidget(QWidget):
    remove_requested = Signal(object)
    open_output_requested = Signal(object)
    retry_requested = Signal(object)
    view_log_requested = Signal(object)

    def __init__(self, job: Job, parent=None) -> None:
        super().__init__(parent)
        self.job = job

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 6, 4, 6)
        outer.setSpacing(10)

        # Left: name + details
        info_box = QVBoxLayout()
        info_box.setSpacing(2)

        self.name_label = QLabel(job.input.name)
        self.name_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.name_label.setToolTip(job.input_path)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #777; font-size: 11px;")

        self.progress = QProgressBar()
        self.progress.setObjectName("jobProgress")
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()

        info_box.addWidget(self.name_label)
        info_box.addWidget(self.detail_label)
        info_box.addWidget(self.progress)
        outer.addLayout(info_box, 1)

        # Right: status + actions
        right = QVBoxLayout()
        right.setSpacing(2)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.open_btn = QPushButton("Open PDF")
        self.retry_btn = QPushButton("Retry")
        self.log_btn = QPushButton("Log")
        self.remove_btn = QPushButton("Remove")
        for btn in (self.open_btn, self.retry_btn, self.log_btn, self.remove_btn):
            btn.setMinimumHeight(30)
            btn.setObjectName("quietButton")
            buttons.addWidget(btn)
        self.remove_btn.setObjectName("dangerButton")
        buttons.addStretch()
        right.addLayout(buttons)
        outer.addLayout(right)

        self.open_btn.clicked.connect(lambda: self.open_output_requested.emit(self.job))
        self.retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.job))
        self.log_btn.clicked.connect(lambda: self.view_log_requested.emit(self.job))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.job))

        self.refresh()

    def refresh(self) -> None:
        job = self.job
        self.name_label.setText(job.input.name)
        self.name_label.setToolTip(job.input_path)

        size_mb = job.file_size / (1024 * 1024)
        parts = []
        if job.page_count:
            parts.append(f"{job.page_count} pages")
        if size_mb >= 0.1:
            parts.append(f"{size_mb:.1f} MB")
        if job.has_text is True:
            parts.append("text detected")
        elif job.has_text is False:
            parts.append("image scan")
        detail = "  |  ".join(parts)

        if job.status == JobStatus.PROCESSING and job.progress_total:
            pct = int(job.progress_current * 100 / job.progress_total) if job.progress_total else 0
            detail += f"  |  {job.stage} {job.progress_current} / {job.progress_total} ({pct}%)"
            self.progress.setValue(pct)
            self.progress.show()
        elif job.status == JobStatus.COMPLETED and job.output_path:
            detail += f"  |  Output: {Path(job.output_path).name}"
            self.detail_label.setToolTip(job.output_path)
        elif job.status == JobStatus.FAILED:
            detail += "  |  " + (job.error_message or "Failed")
        self.detail_label.setText(detail)
        if job.status != JobStatus.PROCESSING:
            self.progress.hide()

        color = _STATUS_COLORS.get(job.status, "#8a8a8a")
        self.status_label.setText(job.status.value)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600; font-size: 11px;")

        terminal = job.is_terminal
        self.open_btn.setVisible(terminal and job.status == JobStatus.COMPLETED)
        self.retry_btn.setVisible(terminal)
        self.log_btn.setVisible(terminal and job.status == JobStatus.FAILED)
        self.remove_btn.setVisible(terminal)

        if job.status == JobStatus.PROCESSING:
            self.status_label.setText(f"{job.stage} • {job.status.value}")
