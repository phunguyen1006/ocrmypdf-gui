"""Structured IPC event protocol between worker process and GUI.

The worker writes JSON objects, one per line, to its stdout. The GUI reads
them with QProcess. Never mix plain text and JSON on the event channel.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, TextIO

EVENT_STREAM: TextIO | None = None


def emit(event: dict[str, Any]) -> None:
    """Serialize an event to the worker's stdout (immediately flushed).

    Exceptions (e.g. broken pipe when the GUI died) are swallowed so the
    worker never crashes because of the event channel.
    """
    stream = EVENT_STREAM or sys.stdout
    if stream is None:
        return
    try:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def emit_started(input_path: str, output_path: str, total_pages: int) -> None:
    emit({"type": "started", "input": input_path, "output": output_path, "total_pages": total_pages})


def emit_stage(stage: str, desc: str = "") -> None:
    emit({"type": "stage", "stage": stage, "desc": desc, "at": time.time()})


def emit_progress(current: int, total: int, unit: str = "page") -> None:
    emit({"type": "progress", "current": current, "total": total, "unit": unit, "at": time.time()})


def emit_warning(message: str) -> None:
    emit({"type": "warning", "message": message, "at": time.time()})


def emit_log(level: str, message: str) -> None:
    emit({"type": "log", "level": level, "message": message, "at": time.time()})


def emit_completed(output_path: str, sidecar_path: str = "", duration: float = 0.0) -> None:
    emit(
        {
            "type": "completed",
            "output": output_path,
            "sidecar": sidecar_path,
            "duration": duration,
        }
    )


def emit_skipped(message: str) -> None:
    emit({"type": "skipped", "message": message, "at": time.time()})


def emit_failed(message: str, error_type: str, exit_code: int | None, traceback: str = "") -> None:
    emit(
        {
            "type": "failed",
            "message": message,
            "error_type": error_type,
            "exit_code": exit_code,
            "traceback": traceback,
            "at": time.time(),
        }
    )


def emit_cancelled(message: str = "Cancelled by user.") -> None:
    emit({"type": "cancelled", "message": message, "at": time.time()})


class EventProgressBar:
    """OCRmyPDF ProgressBar protocol implementation that emits events.

    OCRmyPDF instantiates this class for every group of tasks; desc changes
    per stage (e.g. "OCR", "PDF/A conversion"). We forward everything to the
    GUI which renders stage + page progress and computes ETA.
    """

    def __init__(
        self,
        *,
        total: int | float | None = None,
        desc: str | None = None,
        unit: str | None = None,
        disable: bool = False,
        **kwargs,
    ):
        self.total = total if total is not None else 0
        self.desc = desc or "Processing"
        self.unit = unit or "page"
        self.current = 0.0

    def __enter__(self) -> "EventProgressBar":
        emit_stage(friendly_stage(self.desc), self.desc)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False  # let OCRmyPDF raise

    def update(self, n: float = 1, *, completed: float | None = None) -> None:
        if completed is not None:
            self.current = completed
        else:
            self.current += n
        emit_progress(int(self.current), int(self.total) if self.total else 0, self.unit)


#: Map ocrmypdf's internal stage names to user-friendly labels.
_STAGE_MAP: dict[str, str] = {
    "Scanning contents": "Analyzing PDF",
    "Loading PDF": "Analyzing PDF",
    "OCR": "Recognizing text",
    "PDF/A conversion": "Converting to PDF/A",
    "Optimizing": "Optimizing PDF",
    "metadata": "Generating PDF",
    "Optimizing images": "Optimizing images",
    "postprocessing": "Finalizing",
    "Finalizing": "Finalizing",
    "Linearizing": "Finalizing",
    "Recompressing JPEGs": "Optimizing images",
    "Deflating JPEGs": "Optimizing images",
    "JBIG2": "Optimizing images",
}


def friendly_stage(desc: str) -> str:
    return _STAGE_MAP.get(desc, desc or "Processing")
