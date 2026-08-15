"""Queue manager: owns worker processes, job state machine, IPC parsing.

Each job runs in its own QProcess (python -m app.main --worker in dev,
app.exe --worker when frozen). A worker crash only marks the job as
failed; the GUI keeps running.
"""
from __future__ import annotations

import logging
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from app.core.ocr_options import resolve_output_path
from app.models.job import Job, JobStatus

log = logging.getLogger("app.queue")

GRACEFUL_WAIT_MS = 35_000  # slightly more than the worker's own grace period

CANCEL_MSG = '{"type": "cancel"}\n'


def _app_root() -> Path:
    """Project root in source tree (parent of the app package)."""
    return Path(__file__).resolve().parents[2]


def _worker_command() -> tuple[list[str], str | None]:
    """Return (argv, working_directory) for spawning a worker."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"], None
    exe = sys.executable
    if sys.platform == "win32":
        # Use pythonw.exe in dev so the worker never flashes a console.
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return [exe, "-m", "app.main", "--worker"], str(_app_root())


class QueueManager(QObject):
    """State machine + process supervisor for the OCR queue."""

    job_updated = Signal(object)  # Job
    job_finished = Signal(object)  # Job (terminal state)
    queue_progress = Signal(int, int)  # finished jobs / total
    worker_log = Signal(str, str)  # level, message
    status_changed = Signal(bool, bool)  # running, paused

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: list[Job] = []
        self._job_by_process: dict[QProcess, Job] = {}
        self._paused = False
        self._running = False
        self._cancel_pending: set[str] = set()  # job ids with cancel requested
        self._buffers: dict[QProcess, bytearray] = {}
        self._diagnostics: dict[QProcess, list[str]] = {}
        self._outcomes: dict[QProcess, str] = {}
        self._process_errors: dict[QProcess, str] = {}
        self._concurrent_files = 1
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(8000)
        self._heartbeat.timeout.connect(self._send_heartbeats)

    # ------------------------------------------------------------------ API

    def set_concurrency(self, n: int) -> None:
        self._concurrent_files = max(1, n)

    def enqueue(self, jobs: list[Job]) -> None:
        """Add jobs, skipping duplicates with identical input+output."""
        existing = {self._job_key(j) for j in self._jobs}
        added = 0
        for job in jobs:
            if self._job_key(job) in existing:
                continue
            job.status = JobStatus.WAITING
            self._jobs.append(job)
            existing.add(self._job_key(job))
            self.job_updated.emit(job)
            added += 1
        if added:
            self.queue_progress.emit(self._finished_count(), len(self._jobs))

    def start(self) -> None:
        """Start processing (unpause + launch workers)."""
        if not self._jobs:
            return
        self._paused = False
        self._running = True
        self.status_changed.emit(self._running, self._paused)
        self._maybe_start_next()

    def pause_queue(self) -> None:
        """Finish current jobs, then do not start new ones."""
        self._paused = True
        self.status_changed.emit(self._running, self._paused)

    def resume_queue(self) -> None:
        self.start()

    def cancel_current(self) -> None:
        """Request graceful cancellation of all running workers."""
        for process, job in list(self._job_by_process.items()):
            if job.status == JobStatus.PROCESSING and process.state() != QProcess.ProcessState.NotRunning:
                self._cancel_pending.add(job.id)
                process.write(CANCEL_MSG.encode("utf-8"))
                process.closeWriteChannel()
                # Hard kill fallback if the worker ignores the request.
                QTimer.singleShot(GRACEFUL_WAIT_MS, lambda p=process: self._force_kill(p))

    def retry(self, job: Job) -> None:
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.SKIPPED, JobStatus.COMPLETED):
            return
        job.set_status(JobStatus.WAITING)
        job.error_message = ""
        job.error_detail = ""
        job.progress_current = 0
        job.stage = ""
        if job.output_path and Path(job.output_path).exists():
            from app.models.settings import AppSettings

            settings = self._settings_for(job)
            job.output_path = str(resolve_output_path(job.input, AppSettings.from_dict(settings)))
        self.job_updated.emit(job)
        self.queue_progress.emit(self._finished_count(), len(self._jobs))
        if self._running and not self._paused:
            self._maybe_start_next()

    def remove_job(self, job: Job) -> None:
        if job.status in (JobStatus.PREPARING, JobStatus.PROCESSING):
            return
        if job in self._jobs:
            self._jobs.remove(job)
            self.job_updated.emit(job)
            self.queue_progress.emit(self._finished_count(), len(self._jobs))

    def clear_finished(self) -> None:
        self._jobs = [j for j in self._jobs if not j.is_terminal]
        self.queue_progress.emit(self._finished_count(), len(self._jobs))

    def jobs(self) -> list[Job]:
        return list(self._jobs)

    def has_pending(self) -> bool:
        return any(j.status in (JobStatus.WAITING, JobStatus.PREPARING) for j in self._jobs) or bool(
            self._job_by_process
        )

    def begin_preparation(self, jobs: list[Job], stage: str = "Preparing languages") -> None:
        """Make language preflight visible in queue rows before OCR starts."""
        for job in jobs:
            if job.status != JobStatus.WAITING:
                continue
            job.set_status(JobStatus.PREPARING)
            job.stage = stage
            job.progress_current = 0
            job.progress_total = job.page_count or 0
            job.error_message = ""
            job.error_detail = ""
            self.job_updated.emit(job)

    def update_preparation(self, job: Job, stage: str, current: int = 0, total: int = 0) -> None:
        if job.status != JobStatus.PREPARING:
            return
        job.stage = stage
        job.progress_current = max(0, int(current))
        if total:
            job.progress_total = max(0, int(total))
        self.job_updated.emit(job)

    def finish_preparation(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.status == JobStatus.PREPARING:
                job.set_status(JobStatus.WAITING)
                job.stage = ""
                job.progress_current = 0
                job.progress_total = job.page_count or 0
                self.job_updated.emit(job)

    def fail_preparation(self, jobs: list[Job], message: str, detail: str = "") -> None:
        for job in jobs:
            if job.status != JobStatus.PREPARING:
                continue
            job.set_status(JobStatus.FAILED)
            job.stage = ""
            job.error_message = message
            job.error_detail = detail
            self.job_finished.emit(job)
            self.job_updated.emit(job)
        self.queue_progress.emit(self._finished_count(), len(self._jobs))

    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def stop_all(self) -> None:
        """Called on app close: cancel everything and kill processes."""
        self._running = False
        self._paused = False
        self._heartbeat.stop()
        for process, job in list(self._job_by_process.items()):
            self._cancel_pending.add(job.id)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(5000)
            if process in self._job_by_process:
                self._job_by_process.pop(process, None)
                self._buffers.pop(process, None)
                self._diagnostics.pop(process, None)
                self._outcomes.pop(process, None)
                self._process_errors.pop(process, None)
                process.deleteLater()

    # -------------------------------------------------------------- internals

    def _finished_count(self) -> int:
        return sum(1 for j in self._jobs if j.is_terminal)

    @staticmethod
    def _job_key(job: Job) -> tuple[str, str]:
        def canonical(value: str) -> str:
            try:
                return str(Path(value).resolve(strict=False)).casefold()
            except OSError:
                return str(Path(value)).casefold()

        return canonical(job.input_path), canonical(job.output_path)

    def _maybe_start_next(self) -> None:
        if self._paused or not self._running:
            return
        while len(self._job_by_process) < self._concurrent_files:
            next_job = next((j for j in self._jobs if j.status == JobStatus.WAITING), None)
            if next_job is None:
                break
            self._launch(next_job)

    def _launch(self, job: Job) -> None:
        job.set_status(JobStatus.PROCESSING)
        job.progress_current = 0
        job.progress_total = job.page_count or 0
        job.stage = "Starting"
        job.started_at = str(time.time())
        self.job_updated.emit(job)

        argv, cwd = _worker_command()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        if sys.platform == "win32" and hasattr(process, "setCreateProcessArgumentsModifier"):
            # PyQt5/Qt5 only; Qt6/PySide6 hides consoles via pythonw.exe instead.
            process.setCreateProcessArgumentsModifier(lambda args: self._hide_console(args))
        process.readyReadStandardOutput.connect(lambda: self._read_stdout(process))
        process.readyReadStandardError.connect(lambda: self._read_stderr(process))
        process.errorOccurred.connect(lambda error: self._on_error(process, error))
        process.finished.connect(lambda code, status: self._on_finished(process, code, status))
        if cwd:
            process.setWorkingDirectory(cwd)
        self._buffers[process] = bytearray()
        self._diagnostics[process] = []
        self._outcomes[process] = ""
        self._process_errors[process] = ""
        self._job_by_process[process] = job

        payload = {
            "job": job.to_dict(),
            "settings": self._settings_for(job),
        }
        process.start(argv[0], argv[1:])
        process.write((json_dumps(payload) + "\n").encode("utf-8"))
        # NOTE: do NOT closeWriteChannel() here. EOF on the worker's stdin is
        # interpreted as a dead parent; we keep the channel open and send
        # heartbeat pings instead (see _send_heartbeats).
        if not self._heartbeat.isActive():
            self._heartbeat.start()
        self.job_updated.emit(job)

    def _send_heartbeats(self) -> None:
        if not self._job_by_process:
            self._heartbeat.stop()
            return
        for process in self._job_by_process:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.write(b'{"type": "ping"}\n')

    @staticmethod
    def _hide_console(args) -> None:
        try:
            if sys.platform == "win32":
                creation_flags = args.creationFlags | 0x08000000  # CREATE_NO_WINDOW
                args.creationFlags = creation_flags
        except Exception:
            pass

    def _settings_for(self, job: Job) -> dict:
        """Decode the settings snapshot stored on the job."""
        from app.models.settings import AppSettings

        if job.settings_json:
            try:
                import json

                return AppSettings.from_dict(json.loads(job.settings_json)).to_dict()
            except Exception:
                pass
        return AppSettings().to_dict()

    def _read_stdout(self, process: QProcess) -> None:
        data = process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        buf = self._buffers.get(process)
        if buf is None:
            return
        buf.extend(data.encode("utf-8", errors="replace"))
        while b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            buf[:] = rest
            self._handle_event(process, line.decode("utf-8", errors="replace"))

    def _read_stderr(self, process: QProcess) -> None:
        data = process.readAllStandardError().data().decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._record_diagnostic(process, line)
            self.worker_log.emit("stderr", line)

    def _record_diagnostic(self, process: QProcess, line: str) -> None:
        line = line.strip()
        if not line:
            return
        diagnostics = self._diagnostics.setdefault(process, [])
        diagnostics.append(line)
        del diagnostics[:-80]

    def _on_error(self, process: QProcess, error) -> None:
        message = process.errorString() or "The OCR worker could not be started."
        self._process_errors[process] = message
        self.worker_log.emit("error", message)

    def _handle_event(self, process: QProcess, line: str) -> None:
        job = self._job_by_process.get(process)
        if job is None:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self._record_diagnostic(process, line)
            self.worker_log.emit("info", line.strip())
            return

        etype = event.get("type")
        if etype == "started":
            job.output_path = event.get("output", job.output_path)
            job.progress_total = event.get("total_pages") or job.progress_total
            job.stage = "Analyzing"
        elif etype == "stage":
            job.stage = event.get("stage", job.stage)
            job.progress_current = 0
        elif etype == "progress":
            job.progress_current = event.get("current", job.progress_current)
            total = event.get("total") or job.progress_total
            if total:
                job.progress_total = total
        elif etype == "warning":
            self.worker_log.emit("warning", event.get("message", ""))
        elif etype == "log":
            self.worker_log.emit(event.get("level", "info"), event.get("message", ""))
        elif etype == "completed":
            job.output_path = event.get("output", job.output_path)
            job.output_sidecar = event.get("sidecar", "")
            self._outcomes[process] = "completed"
        elif etype == "failed":
            job.error_message = event.get("message", "OCR failed.")
            job.error_detail = event.get("traceback", "")
            self._outcomes[process] = "failed"
        elif etype == "cancelled":
            job.error_message = event.get("message", "Cancelled.")
            self._outcomes[process] = "cancelled"
        elif etype == "skipped":
            job.error_message = event.get("message", "Skipped.")
            self._outcomes[process] = "skipped"
        self.job_updated.emit(job)

    def _on_finished(self, process: QProcess, exit_code: int, exit_status) -> None:
        # A final event may be buffered just before the process exits.
        self._read_stdout(process)
        self._read_stderr(process)

        job = self._job_by_process.pop(process, None)
        self._buffers.pop(process, None)
        diagnostics = self._diagnostics.pop(process, [])
        outcome = self._outcomes.pop(process, "")
        process_error = self._process_errors.pop(process, "")
        process.deleteLater()
        if job is None:
            return

        cancelled = job.id in self._cancel_pending
        self._cancel_pending.discard(job.id)

        if job.status == JobStatus.PROCESSING:
            if cancelled or outcome == "cancelled":
                job.set_status(JobStatus.CANCELLED)
                job.error_message = job.error_message or "Cancelled."
            elif outcome == "skipped":
                job.set_status(JobStatus.SKIPPED)
            elif outcome == "completed" and exit_code == 0:
                job.set_status(JobStatus.COMPLETED)
            else:
                job.set_status(JobStatus.FAILED)
                if not job.error_message:
                    detail = process_error or f"OCR process failed (exit code {exit_code})."
                    job.error_message = detail
                if diagnostics:
                    job.error_detail = "\n".join(diagnostics)
                    if not process_error:
                        job.error_message = diagnostics[-1]
            if job.started_at:
                try:
                    job.duration_seconds = max(0.0, time.time() - float(job.started_at))
                except (TypeError, ValueError):
                    job.duration_seconds = 0.0
            self.job_finished.emit(job)
        self.job_updated.emit(job)
        self.queue_progress.emit(self._finished_count(), len(self._jobs))

        if not self.has_pending():
            self._running = False
            self.status_changed.emit(self._running, self._paused)
        self._maybe_start_next()

    def _force_kill(self, process: QProcess) -> None:
        job = self._job_by_process.get(process)
        if job is not None and job.id in self._cancel_pending:
            log.warning("Worker did not stop in time; killing process")
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
