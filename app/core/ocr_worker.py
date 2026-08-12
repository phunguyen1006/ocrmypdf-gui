"""OCR worker subprocess.

Runs in a separate process (launched by the GUI via QProcess) and performs
the actual OCR using the OCRmyPDF Python API. Communicates with the GUI
exclusively through structured JSON events on stdout:

    {"type": "started"|"stage"|"progress"|"warning"|"log"|"completed"|"failed"|"cancelled", ...}

The job description arrives as a single JSON line on stdin; further stdin
lines carry control messages. The GUI keeps the stdin pipe open and sends
heartbeat pings; the worker cancels the job if the parent stops responding
or explicitly requests cancellation.

A crash in this process never affects the GUI.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ocrmypdf import ExitCode

from app.core import progress
from app.core.ocr_options import build_options, estimate_job_work, resolve_output_path
from app.models.job import Job
from app.models.settings import AppSettings
from app.utils import exceptions as exc_utils
from app.utils.paths import app_temp_dir, make_work_dir
from app.utils.processes import install_hidden_ocrmypdf_subprocesses

log = logging.getLogger("app.worker")

GRACEFUL_SHUTDOWN_WAIT = 30.0
HEARTBEAT_TIMEOUT = 30.0

_plugin_path = Path(__file__).resolve().parent / "ocr_progress_plugin.py"
if not _plugin_path.exists():
    # Frozen (PyInstaller): the plugin lives inside the bundle as a module.
    _plugin_path = "app.core.ocr_progress_plugin"

_PLUGIN_SPEC = _plugin_path


class _EventLogHandler(logging.Handler):
    """Forward log records to the GUI as structured events."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            level = record.levelname.lower()
            if record.levelno >= logging.WARNING:
                progress.emit_warning(message)
            else:
                progress.emit_log(level, message)
        except Exception:  # never let logging break the worker
            pass


def _read_job_from_stdin() -> dict[str, Any] | None:
    """Read the job JSON from the first stdin line. None if parent died."""
    try:
        line = sys.stdin.buffer.readline()
    except (OSError, ValueError):
        return None
    if not line:
        return None
    try:
        return json.loads(line.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


class _StdinWatcher:
    """Watches stdin for cancel messages and GUI heartbeats."""

    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.last_message_at = time.monotonic()

    def start(self) -> None:
        threading.Thread(target=self._run, name="stdin-watcher", daemon=True).start()

    def _run(self) -> None:
        try:
            while True:
                line = sys.stdin.buffer.readline()
                if not line:
                    return
                self.last_message_at = time.monotonic()
                try:
                    data = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "cancel":
                    self.cancel_event.set()
                    return
        except (OSError, ValueError):
            pass

    def parent_may_be_dead(self, timeout: float = HEARTBEAT_TIMEOUT) -> bool:
        return time.monotonic() - self.last_message_at > timeout


def _request_cancel_in_thread(thread: threading.Thread) -> bool:
    """Raise KeyboardInterrupt in the OCR thread (CPython)."""
    if thread.ident is None:
        return False
    tid = ctypes.c_ulong(thread.ident)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(KeyboardInterrupt))
    if res == 0:
        return False
    return True


def _warm_plugin_namespaces(options) -> None:
    """Pre-resolve ocrmypdf plugin option namespaces in the parent process.

    ocrmypdf 17.x resolves namespaces like ``options.tesseract`` lazily using
    a module-global registry, which is empty inside spawned child processes.
    Accessing them here warms the per-object cache (extra_attrs), so the
    pickled options work correctly in ProcessPoolExecutor workers.
    """
    for namespace in ("tesseract", "optimize", "ghostscript", "pdf_renderer"):
        try:
            getattr(options, namespace)
        except AttributeError:
            continue


def _cleanup_work_dir(work_dir: Path | None) -> None:
    if work_dir is None or not work_dir.exists():
        return
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        log.debug("Could not fully remove work dir %s", work_dir)


def _cleanup_stale_tmp() -> None:
    """Remove leftover work dirs from crashed previous sessions (older than 1h)."""
    base = app_temp_dir()
    if not base.exists():
        return
    cutoff = time.time() - 3600
    try:
        for entry in base.iterdir():
            if not entry.name.startswith("ocr-tmp-"):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def run_ocr_job(job: Job, settings: AppSettings) -> int:
    """Execute one OCR job. Returns a process exit code (0 on success)."""
    input_path = Path(job.input_path)
    output_path = Path(job.output_path) if job.output_path else resolve_output_path(input_path, settings)

    if not input_path.exists() or not input_path.is_file():
        progress.emit_failed(
            "The input PDF could not be found or read.",
            "InputFileError",
            None,
        )
        return 1
    if os.path.normcase(os.path.abspath(input_path)) == os.path.normcase(os.path.abspath(output_path)):
        progress.emit_failed(
            "The output file must be different from the input PDF.",
            "BadArgsError",
            None,
        )
        return 1

    # An empty selection means that every page was excluded. Passing an empty
    # set to OCRmyPDF would be ambiguous, so make the outcome explicit.
    if job.pages == []:
        progress.emit_started(str(input_path), str(output_path), 0)
        progress.emit_skipped("No pages were selected for OCR.")
        return 0

    work_dir: Path | None = None
    final_sidecar_path: Path | None = None
    staged_output_path: Path | None = None
    staged_sidecar_path: Path | None = None
    try:
        work_dir = make_work_dir()
        final_sidecar_path = output_path.with_suffix(".txt") if settings.sidecar else None
        staged_output_path = work_dir / output_path.name
        staged_sidecar_path = work_dir / (final_sidecar_path.name if final_sidecar_path else "sidecar.txt")
        if settings.sidecar:
            sidecar_path = staged_sidecar_path
        else:
            sidecar_path = None

        page_selection = job.pages if job.pages is not None else None
        options, work_dir = build_options(
            input_path=input_path,
            settings=settings,
            output_path=staged_output_path,
            pages=page_selection,
            work_folder=work_dir,
            sidecar_path=sidecar_path,
        )
    except Exception as exc:  # validation failed before OCR started
        progress.emit_failed(
            exc_utils.friendly_exception_message(exc),
            exc.__class__.__name__,
            None,
            exc_utils.format_traceback(exc),
        )
        return 1

    total_units = estimate_job_work(settings, page_selection, job.page_count or 1)
    progress.emit_started(str(input_path), str(output_path), total_units)

    result: dict[str, Any] = {}
    started = time.monotonic()

    def _run() -> None:
        try:
            install_hidden_ocrmypdf_subprocesses()
            from ocrmypdf import api

            # 1. Register plugin models (populates options.tesseract etc.).
            plugin_manager = api.setup_plugin_infrastructure(plugins=[_PLUGIN_SPEC])
            # 2. Warm namespace cache in this (parent) process; child processes
            #    receive the pickled, fully-resolved namespace objects.
            _warm_plugin_namespaces(options)
            # 3. Run the pipeline with the pre-configured plugin manager.
            exit_code = api.ocr(
                options,
                plugin_manager=plugin_manager,
            )
            result["exit_code"] = int(exit_code)
        except BaseException as exc:  # noqa: BLE001 - must never crash silently
            result["exception"] = exc

    ocr_thread = threading.Thread(target=_run, name="ocr", daemon=True)
    ocr_thread.start()

    watcher = _StdinWatcher()
    watcher.start()

    cancelled = False
    while ocr_thread.is_alive():
        if watcher.cancel_event.is_set() or watcher.parent_may_be_dead():
            cancelled = True
            log.info("Cancel requested; interrupting OCR pipeline")
            _request_cancel_in_thread(ocr_thread)
            break
        time.sleep(0.1)

    ocr_thread.join(timeout=GRACEFUL_SHUTDOWN_WAIT)
    if ocr_thread.is_alive():
        log.error("OCR thread did not stop gracefully; forcing exit")
        progress.emit_cancelled("Could not stop OCR cleanly; process was terminated.")
        _cleanup_work_dir(work_dir)
        return 130

    duration = time.monotonic() - started

    exception = result.get("exception")
    if exception is not None:
        if isinstance(exception, KeyboardInterrupt):
            progress.emit_cancelled()
            _cleanup_work_dir(work_dir)
            return 130
        friendly = exc_utils.friendly_exception_message(exception)
        exit_code = getattr(exception, "exit_code", None)
        if exit_code is None and hasattr(exception, "code"):
            exit_code = exception.code
        if isinstance(exit_code, ExitCode):
            exit_code = int(exit_code)
        if exit_code == ExitCode.ctrl_c:
            progress.emit_cancelled()
            _cleanup_work_dir(work_dir)
            return 130
        progress.emit_failed(friendly, exception.__class__.__name__, exit_code, exc_utils.format_traceback(exception))
        _cleanup_work_dir(work_dir)
        return exit_code if isinstance(exit_code, int) else 1

    if cancelled or result.get("exit_code") == ExitCode.ctrl_c:
        progress.emit_cancelled()
        _cleanup_work_dir(work_dir)
        return 130

    exit_code = result.get("exit_code")
    if exit_code != 0:
        progress.emit_failed(exc_utils.exit_code_message(exit_code), "ExitCodeError", exit_code)
        _cleanup_work_dir(work_dir)
        return exit_code

    if staged_output_path is None or not staged_output_path.exists():
        progress.emit_failed(
            "OCR finished but no output PDF was created.",
            "InvalidOutputError",
            None,
        )
        _cleanup_work_dir(work_dir)
        return 1

    # OCRmyPDF writes into the per-job work folder. Only publish the final PDF
    # after the pipeline has succeeded, so a crash cannot corrupt the user's
    # destination file.
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise FileExistsError(str(output_path))
        if final_sidecar_path is not None and final_sidecar_path.exists():
            raise FileExistsError(str(final_sidecar_path))
        staged_output_path.replace(output_path)
        if staged_sidecar_path is not None and staged_sidecar_path.exists() and final_sidecar_path is not None:
            staged_sidecar_path.replace(final_sidecar_path)
    except Exception as exc:  # noqa: BLE001 - surface as a friendly event
        progress.emit_failed(
            exc_utils.friendly_exception_message(exc),
            exc.__class__.__name__,
            None,
            exc_utils.format_traceback(exc),
        )
        # The PDF was published by this block, so remove it if sidecar
        # publication failed; this keeps the pair all-or-nothing in practice.
        if final_sidecar_path is not None and not final_sidecar_path.exists() and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        _cleanup_work_dir(work_dir)
        return 1

    sidecar = ""
    if final_sidecar_path is not None and final_sidecar_path.exists():
        sidecar = str(final_sidecar_path)
    progress.emit_completed(str(output_path), sidecar, duration)
    _cleanup_work_dir(work_dir)
    return 0


def run_worker() -> int:
    """Entry point for the worker process mode."""
    progress.EVENT_STREAM = sys.stdout

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_EventLogHandler())

    # Forward ocrmypdf's own messages (warnings from children included).
    # ocrmypdf INFO chatter ("Preprocessing...", "Postprocessing...") is
    # not useful in the GUI log; WARNING+ (page skipped, missing engine) is.
    logging.getLogger("ocrmypdf").setLevel(logging.WARNING)
    for noisy in ("fontTools", "fontTools.subset", "pikepdf", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)

    _cleanup_stale_tmp()

    job_data = _read_job_from_stdin()
    if job_data is None:
        progress.emit_failed("The OCR process did not receive a job.", "BadJobError", None)
        return 1

    job = Job.from_dict(job_data.get("job", job_data))
    settings_raw = job_data.get("settings", {})
    settings = AppSettings.from_dict(settings_raw) if settings_raw else AppSettings()

    try:
        return run_ocr_job(job, settings)
    except SystemExit:
        raise
    except Exception as exc:  # last-resort guard
        log.error("Worker fatal error: %s", exc, exc_info=True)
        progress.emit_failed(
            exc_utils.friendly_exception_message(exc),
            exc.__class__.__name__,
            None,
            exc_utils.format_traceback(exc),
        )
        return 1


def main() -> None:
    code = run_worker()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # ensure no lingering threads keep the process alive


if __name__ == "__main__":
    main()
