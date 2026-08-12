"""Logging helpers shared by GUI and worker process."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.utils.paths import app_log_dir, ensure_app_dirs

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_DATEFMT = "%H:%M:%S"


def configure_logging(*, level: int = logging.INFO, file: Path | None = None) -> Path:
    """Configure a shared file logger plus stderr console handler.

    Returns the log file path actually used.
    """
    ensure_app_dirs()
    if file is None:
        file = app_log_dir() / "app.log"

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    fh = logging.FileHandler(file, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Do not spam the console when frozen; the GUI has its own log panel.
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    # Keep OCRmyPDF's own chatter out of the console; it is captured into the
    # log file above.
    logging.getLogger("ocrmypdf").setLevel(logging.WARNING)

    return file


def make_log_filename(job_id: str) -> Path:
    return app_log_dir() / f"job-{job_id}.log"