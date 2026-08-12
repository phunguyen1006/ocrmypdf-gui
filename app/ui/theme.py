"""Monochrome visual system for the desktop application.

The UI intentionally uses a small token set: white surfaces, near-black ink,
and grayscale borders. Semantic error/success states are still explicit in
text, so status is never communicated by color alone.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


INK = "#111111"
INK_MUTED = "#5f5f5f"
SURFACE = "#ffffff"
SURFACE_SUBTLE = "#f6f6f6"
BORDER = "#d8d8d8"
BORDER_STRONG = "#111111"
ERROR = "#9f1d1d"


MONOCHROME_STYLESHEET = f"""
QWidget {{
    color: {INK};
    background: {SURFACE};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {SURFACE};
}}
QLabel#eyebrow {{
    color: {INK_MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#appTitle {{
    color: {INK};
    font-size: 24px;
    font-weight: 700;
}}
QLabel#appSubtitle, QLabel#mutedLabel {{
    color: {INK_MUTED};
}}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#dropZone {{
    background: {SURFACE_SUBTLE};
    border: 1px dashed {BORDER_STRONG};
    border-radius: 14px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: #eeeeee;
    border: 2px solid {BORDER_STRONG};
}}
QListWidget#queueList {{
    background: {SURFACE};
    border: 0;
    outline: 0;
    padding: 8px;
}}
QListWidget#queueList::item {{
    border-bottom: 1px solid {BORDER};
    padding: 4px 0;
}}
QListWidget#queueList::item:selected {{
    background: {SURFACE_SUBTLE};
    color: {INK};
}}
QPushButton {{
    min-height: 36px;
    padding: 0 15px;
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
    color: {INK};
    font-weight: 600;
}}
QPushButton:hover {{
    background: {SURFACE_SUBTLE};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background: #eaeaea;
}}
QPushButton:disabled {{
    color: #989898;
    background: #f4f4f4;
    border-color: #e4e4e4;
}}
QPushButton#primaryButton {{
    background: {INK};
    color: {SURFACE};
    border-color: {INK};
    min-height: 42px;
    padding: 0 24px;
}}
QPushButton#primaryButton:hover {{
    background: #2f2f2f;
    border-color: #2f2f2f;
}}
QPushButton#primaryButton:pressed {{
    background: #000000;
}}
QPushButton#textButton, QPushButton#quietButton {{
    min-height: 32px;
    padding: 0 10px;
    border-color: transparent;
    background: transparent;
}}
QPushButton#textButton:hover, QPushButton#quietButton:hover {{
    background: {SURFACE_SUBTLE};
    border-color: {BORDER};
}}
QPushButton#dangerButton {{
    color: {ERROR};
    border-color: #d8aaaa;
}}
QComboBox, QLineEdit, QSpinBox {{
    min-height: 36px;
    padding: 0 10px;
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
    color: {INK};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {BORDER_STRONG};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QAbstractButton:focus {{
    border: 2px solid {BORDER_STRONG};
}}
QCheckBox {{
    min-height: 34px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {INK};
    image: none;
}}
QGroupBox {{
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    background: {SURFACE};
}}
QProgressBar {{
    min-height: 8px;
    max-height: 8px;
    border: 0;
    border-radius: 4px;
    background: #e8e8e8;
    text-align: center;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: {INK};
}}
QStatusBar {{
    color: {INK_MUTED};
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QToolTip {{
    color: {INK};
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    padding: 6px;
}}
QScrollArea#settingsScroll {{
    background: {SURFACE};
    border: 0;
}}
QScrollBar:vertical {{
    width: 10px;
    margin: 2px 0 2px 2px;
    background: {SURFACE_SUBTLE};
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    min-height: 32px;
    background: #bdbdbd;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {INK_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QDockWidget {{
    font-weight: 700;
}}
"""


def apply_monochrome_theme(app: QApplication) -> None:
    """Apply the palette and stylesheet once at application startup."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(INK))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(INK))
    app.setPalette(palette)
    app.setStyleSheet(MONOCHROME_STYLESHEET)
