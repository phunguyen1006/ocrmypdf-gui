from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_settings_dialog_has_scrollable_content_and_sticky_footer(qapp) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

    from app.models.settings import AppSettings
    from app.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(AppSettings())
    dialog.resize(520, 430)
    dialog.show()
    qapp.processEvents()
    scroll = dialog.findChild(QScrollArea, "settingsScroll")
    footer = dialog.findChild(QDialogButtonBox, "settingsFooter")
    assert scroll is not None
    assert footer is not None
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.verticalScrollBar().maximum() > 0
    assert footer.geometry().bottom() <= dialog.rect().bottom()
    dialog.close()


def test_language_picker_lists_catalogue_without_network(qapp) -> None:
    from app.models.settings import AppSettings
    from app.services.tesseract_service import TesseractService
    from app.ui.language_dialog import LanguagePickerDialog

    dialog = LanguagePickerDialog(TesseractService(), AppSettings().custom_languages)
    assert len(dialog._models) == 126
    assert dialog.list_widget.count() == 126
    assert dialog.selected_label.text().startswith("Selected: 2")
    dialog.search_edit.setText("Chinese")
    qapp.processEvents()
    assert dialog.list_widget.count() >= 2
    dialog.close()


def test_main_language_controls_keep_multi_language_choice_visible(qapp, tmp_path: Path) -> None:
    from app.models.settings import AppSettings, SettingsStore
    from app.services.history_service import HistoryService
    from app.ui.main_window import MainWindow

    store = SettingsStore(ini_path=tmp_path / "settings.ini")
    store.set_first_run_done(True)
    store.save(AppSettings(language_preset="chi_sim+vie"))
    window = MainWindow(store=store, history=HistoryService(tmp_path / "history.db"))
    assert window.lang_combo.currentData() == "chi_sim+vie"
    assert "Chinese" in window.lang_combo.currentText()
    assert window.lang_combo.findData("custom") < 6
    assert not window.language_picker_btn.isHidden()
    window.close()


def test_start_snapshot_uses_language_selected_after_file_was_added(qapp, tmp_path: Path) -> None:
    import json

    from app.models.job import Job
    from app.models.settings import AppSettings, SettingsStore
    from app.services.history_service import HistoryService
    from app.ui.main_window import MainWindow

    store = SettingsStore(ini_path=tmp_path / "settings.ini")
    store.set_first_run_done(True)
    window = MainWindow(store=store, history=HistoryService(tmp_path / "history.db"))
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    job = Job(str(pdf), settings_json=AppSettings(language_preset="auto").to_json(), page_count=1)
    window.queue.enqueue([job])

    window.lang_combo.setCurrentIndex(window.lang_combo.findData("chi_sim+vie"))
    snapshot = window._snapshot_settings()
    assert window._apply_current_settings_to_waiting([job], snapshot)
    assert json.loads(job.settings_json)["language_preset"] == "chi_sim+vie"
    window.queue.remove_job(job)
    window.close()


def test_low_confidence_review_dialog_has_candidate_checkboxes(qapp) -> None:
    from app.services.language_detection_service import DocumentDetection, PageDetection
    from app.services.tesseract_service import TesseractService
    from app.ui.language_dialog import LanguageReviewDialog

    page = PageDetection(2, ("vie",), 0.4, "latin", ("vie", "eng"))
    detection = DocumentDetection(("vie",), 0.4, (page,), ("vie", "eng"))
    dialog = LanguageReviewDialog("mixed.pdf", detection, TesseractService())
    assert len(dialog.checks) == 2
    assert "vie" in dialog.selected_codes()
    dialog.close()


def test_logo_is_available_in_source_tree(qapp, tmp_path: Path) -> None:
    from app.models.settings import SettingsStore
    from app.ui.main_window import MainWindow
    from app.utils.resources import resource_path

    assert resource_path("assets/ocrmypdf-gui.svg").is_file()
    store = SettingsStore(ini_path=tmp_path / "settings.ini")
    store.set_first_run_done(True)
    window = MainWindow(store=store)
    assert not window.windowIcon().isNull()
    window.close()


def test_resource_path_resolves_frozen_bundle(monkeypatch, tmp_path: Path) -> None:
    import sys

    from app.utils.resources import resource_path

    bundled = tmp_path / "assets"
    bundled.mkdir()
    (bundled / "ocrmypdf-gui.ico").write_bytes(b"icon")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_path("assets/ocrmypdf-gui.ico") == bundled / "ocrmypdf-gui.ico"
