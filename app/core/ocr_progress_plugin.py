"""OCRmyPDF plugin that reports progress via structured events.

Passed to ocrmypdf through the ``plugins=[Path]`` argument. ocrmypdf loads
this module and asks it for a progress bar class via the
``get_progressbar_class`` hook.

This file must stay importable from the app package when frozen.
"""
from __future__ import annotations

from ocrmypdf import hookimpl

from app.core.progress import EventProgressBar


@hookimpl
def get_progressbar_class():
    return EventProgressBar