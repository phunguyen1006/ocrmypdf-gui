"""Progress panel: shown while the current job is being processed."""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

ETA_SAMPLES = 12  # moving average window


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ProgressPanel(QWidget):
    """Live OCR progress: stage, page, percent, elapsed, ETA, cancel."""

    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filename = ""
        self._started = 0.0
        self._samples: deque[tuple[float, float]] = deque(maxlen=ETA_SAMPLES)
        self._total = 0
        self._active = False

        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.file_label = QLabel("")
        self.file_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        root.addWidget(self.file_label)

        self.stage_label = QLabel("")
        self.stage_label.setStyleSheet("color: #555; font-size: 12px;")
        root.addWidget(self.stage_label)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        root.addWidget(self.bar)

        stats = QHBoxLayout()
        self.page_label = QLabel("")
        self.page_label.setStyleSheet("font-size: 12px;")
        self.time_label = QLabel("")
        self.time_label.setStyleSheet("color: #777; font-size: 12px;")
        stats.addWidget(self.page_label)
        stats.addStretch()
        stats.addWidget(self.time_label)
        root.addLayout(stats)

        bottom = QHBoxLayout()
        self.avg_label = QLabel("")
        self.avg_label.setStyleSheet("color: #999; font-size: 11px;")
        bottom.addWidget(self.avg_label)
        bottom.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedWidth(90)
        self.cancel_button.setStyleSheet(
            "QPushButton { background:#fff1f0; color:#c5221f; border:1px solid #e0a8a5; }"
            "QPushButton:hover { background:#ffe0dd; }"
        )
        self.cancel_button.clicked.connect(self.cancel_requested)
        bottom.addWidget(self.cancel_button)
        root.addLayout(bottom)

        self._set_running(False)

    def start_job(self, filename: str, total: int) -> None:
        if self._active and self._filename == filename:
            if total > 0:
                self._total = total
            return
        self._filename = filename
        self._total = total
        self._started = time.monotonic()
        self._samples.clear()
        self.file_label.setText(filename)
        self.stage_label.setText("Starting...")
        self.bar.setValue(0)
        self.page_label.setText(f"0 / {total}")
        self.time_label.setText("Elapsed: 00:00  •  ETA: --:--")
        self.avg_label.setText("")
        self._set_running(True)
        self._active = True

    def update_stage(self, stage: str) -> None:
        self.stage_label.setText(stage)

    def update_progress(self, current: int, total: int) -> None:
        if total:
            self._total = total
            self.bar.setMaximum(total)
            self.bar.setValue(current)
            self.page_label.setText(f"{current} / {total}")
            now = time.monotonic()
            self._samples.append((now, float(current)))

    def update_eta(self) -> None:
        if not self._active:
            return
        now = time.monotonic()
        elapsed = now - self._started
        self.time_label.setText(f"Elapsed: {format_duration(elapsed)}  •  ETA: --:--")
        if not self._samples or len(self._samples) < 2 or self._total <= 0:
            return

        # Moving average over recent samples (not whole-job average).
        first_t, first_c = self._samples[0]
        last_t, last_c = self._samples[-1]
        dt = max(last_t - first_t, 1e-6)
        rate = (last_c - first_c) / dt  # units per second
        if rate <= 0:
            return
        remaining = (self._total - last_c) / rate
        self.time_label.setText(
            f"Elapsed: {format_duration(elapsed)}  •  ETA: {format_duration(remaining)}"
        )
        if self._total and last_c:
            avg = elapsed / last_c
            self.avg_label.setText(f"~{avg:.1f} s/page")

    def finish(self, status_text: str = "") -> None:
        self.stage_label.setText(status_text or self.stage_label.text())
        self._active = False
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.cancel_button.setEnabled(running)
        self.setVisible(running)
