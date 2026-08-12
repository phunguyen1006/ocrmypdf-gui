"""GUI smoke tests (offscreen): window opens, drop zone, queue runs a real OCR job."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QMLSCENE_DEVICE", "softwarecontext")

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def win(qapp, tmp_path: Path):
    from app.models.settings import AppSettings, SettingsStore
    from app.services.history_service import HistoryService
    from app.ui.main_window import MainWindow

    store = SettingsStore(ini_path=str(tmp_path / "settings.ini"))
    store.set_first_run_done(True)  # skip the modal first-run dialog
    store.save(AppSettings(language_preset="vie+eng"))
    history = HistoryService(db_path=str(tmp_path / "history.db"))
    window = MainWindow(store=store, history=history)
    window.show()
    yield window
    for j in list(window.queue.jobs()):
        window.queue.remove_job(j)
    window.queue.stop_all()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def pump_until(cond, timeout=90.0):
    from PySide6.QtCore import QEventLoop, QCoreApplication

    app = QCoreApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)
    return False


def make_scan_pdf(path: Path, pages: int = 2) -> None:
    import io

    import img2pdf
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for candidate in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"):
        try:
            font = ImageFont.truetype(candidate, 48)
            break
        except OSError:
            continue
    images = []
    for i in range(pages):
        img = Image.new("RGB", (1400, 1800), "white")
        d = ImageDraw.Draw(img)
        d.text((100, 120), f"Gui smoke test page {i + 1}", font=font, fill="black")
        d.text((100, 240), "Hello world OCR", font=font, fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        images.append(buf.getvalue())
    path.write_bytes(img2pdf.convert(images))


class TestMainWindow:
    def test_window_opens(self, win):
        assert win.windowTitle() == "OCRmyPDF GUI"
        assert win.queue_list is not None
        assert win.lang_combo is not None

    def test_drop_zone_adds_job(self, win, tmp_path: Path):
        pdf = tmp_path / "scan.pdf"
        make_scan_pdf(pdf)
        win._on_files_dropped([pdf])
        assert win.queue_list.count() == 1
        assert win.queue.jobs()[0].input_path == str(pdf)

    def test_full_queue_run_offscreen(self, win, tmp_path: Path):
        pdf = tmp_path / "scan_full.pdf"
        make_scan_pdf(pdf)
        win._on_files_dropped([pdf])
        win._start()

        ok = pump_until(lambda: win.queue.jobs() and win.queue.jobs()[0].status.value == "Completed")
        assert ok, f"job did not complete in time; statuses={[j.status.value for j in win.queue.jobs()]}"
        job = win.queue.jobs()[0]
        assert job.output_path and Path(job.output_path).exists()
        assert not win.queue.is_running()

    def test_cancel_button_during_run(self, win, tmp_path: Path):
        pdf = tmp_path / "scan_cancel.pdf"
        make_scan_pdf(pdf)
        win._on_files_dropped([pdf])
        win._start()
        running = pump_until(lambda: any(j.status.value == "Processing" for j in win.queue.jobs()))
        assert running, "job never entered Processing state"
        win._cancel()
        ok = pump_until(lambda: win.queue.jobs() and win.queue.jobs()[0].status.value in ("Cancelled", "Failed"))
        assert ok, f"job did not cancel; statuses={[j.status.value for j in win.queue.jobs()]}"
