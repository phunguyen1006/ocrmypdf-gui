"""Windows subprocess helpers used by the OCR worker.

The GUI itself is built with a windowed Python/PyInstaller bootloader, but
OCRmyPDF launches external console programs such as Tesseract and Ghostscript
through its own subprocess wrapper. Those children must inherit the
``CREATE_NO_WINDOW`` flag or Windows shows a console for every page/tool call.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def add_hidden_console_flag(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Add Windows' no-console flag while preserving caller-supplied flags."""
    if sys.platform == "win32":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | CREATE_NO_WINDOW
    return kwargs


def install_hidden_ocrmypdf_subprocesses() -> None:
    """Patch OCRmyPDF's low-level subprocess wrapper once for this worker.

    OCRmyPDF intentionally delegates to the standard library, but does not
    set Windows' ``CREATE_NO_WINDOW`` flag itself. Patching the two aliases
    used by its wrapper covers both ``run`` and streaming ``Popen`` calls
    without modifying the installed third-party package.
    """
    if sys.platform != "win32":
        return

    from ocrmypdf.subprocess import _run as ocrmypdf_run

    if getattr(ocrmypdf_run, "_ocrmypdf_gui_hidden_console", False):
        return

    original_run = ocrmypdf_run.subprocess_run
    original_popen = ocrmypdf_run.Popen

    def hidden_run(*args, **kwargs):
        add_hidden_console_flag(kwargs)
        return original_run(*args, **kwargs)

    def hidden_popen(*args, **kwargs):
        add_hidden_console_flag(kwargs)
        return original_popen(*args, **kwargs)

    ocrmypdf_run.subprocess_run = hidden_run
    ocrmypdf_run.Popen = hidden_popen
    ocrmypdf_run._ocrmypdf_gui_hidden_console = True
