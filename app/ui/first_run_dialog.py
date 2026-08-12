"""First-run welcome dialog with live dependency check."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)

from app.services import dependency_checker
from app.services.dependency_checker import DependencyReport, human_language_name


class FirstRunDialog(QDialog):
    """Shows component status and lets the user fix/refresh dependencies."""

    def __init__(self, report: DependencyReport, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCRmyPDF GUI - Setup")
        self.setMinimumWidth(460)
        self._report = report

        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("Welcome to OCRmyPDF GUI")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        root.addWidget(title)

        subtitle = QLabel("This app turns scanned PDFs into searchable PDFs.\nBelow you can check the OCR components on your computer.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #555;")
        root.addWidget(subtitle)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.fix_btn = QPushButton("Installation instructions")
        self.locate_btn = QPushButton("Locate manually")
        self.refresh_btn = QPushButton("Refresh")
        self.close_btn = QPushButton("Continue")
        self.close_btn.setDefault(True)

        self.fix_btn.clicked.connect(self._open_install_help)
        self.locate_btn.clicked.connect(self._locate)
        self.refresh_btn.clicked.connect(self._refresh)
        self.close_btn.clicked.connect(self.accept)

        buttons.addWidget(self.fix_btn)
        buttons.addWidget(self.locate_btn)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

        self._render()

    def _render(self) -> None:
        report = self._report
        lines = ["<pre style='font-family:Consolas,monospace; font-size:12px;'>"]
        for comp in (report.ocrmypdf, report.tesseract, report.ghostscript):
            if comp.present:
                lines.append(f"  {chr(0x2713)} {comp.name}: {comp.version}")
            elif comp is report.ghostscript:
                lines.append("  - Ghostscript: not found (only needed for PDF/A and some advanced paths)")
            else:
                lines.append(f"  {chr(0x2717)} {comp.name}: <b style='color:#c5221f'>not found</b>")
        if report.tesseract.present:
            for lang in sorted(report.languages):
                if lang in ("osd",):
                    continue
                lines.append(f"  {chr(0x2713)} Language: {human_language_name(lang)} ({lang})")
            if report.languages_error:
                lines.append(f"  {chr(0x2717)} <b style='color:#c5221f'>{report.languages_error}</b>")
        lines.append("</pre>")
        self.status_label.setText("\n".join(lines))

        missing = [c.name for c in (report.ocrmypdf, report.tesseract) if not c.present]
        if not missing and not report.languages_error:
            self.close_btn.setText("Continue")
            self.close_btn.setEnabled(True)
            self.fix_btn.setVisible(False)
        else:
            self.close_btn.setText("Continue anyway")
            self.fix_btn.setVisible(True)
            self.locate_btn.setVisible(bool(missing))

    def _open_install_help(self) -> None:
        webbrowser.open("https://github.com/UB-Mannheim/tesseract/wiki")

    def _locate(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        exe, _ = QFileDialog.getOpenFileName(
            self,
            "Locate tesseract.exe",
            "C:\\Program Files\\Tesseract-OCR",
            "tesseract.exe (tesseract.exe)",
        )
        if not exe:
            return
        if not exe.lower().endswith("tesseract.exe"):
            QMessageBox.warning(self, "Wrong file", "Please select the file named tesseract.exe")
            return
        dependency_checker.TESSERACT_PATHS.insert(0, Path(exe))
        self._refresh()

    def _refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Checking...")
        report = dependency_checker.check_dependencies()
        self._report = report
        self.refresh_btn.setText("Refresh")
        self.refresh_btn.setEnabled(True)
        self._render()
