"""Application entry point.

Modes:
    python -m app.main            -> starts the GUI
    python -m app.main --worker   -> runs the OCR worker process
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the app package importable when running from the source tree.
_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))


def main() -> int:
    if "--worker" in sys.argv:
        from app.core.ocr_worker import main as worker_main

        worker_main()
        return 0

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon

    from app.models.settings import SettingsStore
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_monochrome_theme
    from app.utils import logging as app_logging
    from app.utils.paths import ensure_app_dirs
    from app.utils.resources import resource_path

    ensure_app_dirs()
    app_logging.configure_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("OCRmyPDF GUI")
    app.setOrganizationName("OCRmyPDF GUI")
    app.setStyle("Fusion")
    icon_path = resource_path("assets/ocrmypdf-gui.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_monochrome_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
