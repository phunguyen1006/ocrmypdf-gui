from __future__ import annotations

from pathlib import Path

from app.core.queue_manager import _worker_completed_successfully
from app.models.job import Job


def test_zero_exit_with_published_output_recovers_missing_completed_event(tmp_path: Path) -> None:
    output = tmp_path / "book (OCR).pdf"
    output.write_bytes(b"%PDF-1.4\n%%EOF")
    job = Job(str(tmp_path / "book.pdf"), output_path=str(output))

    assert _worker_completed_successfully(job, outcome="", exit_code=0)


def test_zero_exit_does_not_hide_explicit_failure_or_missing_output(tmp_path: Path) -> None:
    missing = Job(str(tmp_path / "book.pdf"), output_path=str(tmp_path / "missing.pdf"))
    existing = tmp_path / "existing.pdf"
    existing.write_bytes(b"%PDF-1.4\n%%EOF")
    failed = Job(str(tmp_path / "book.pdf"), output_path=str(existing))

    assert not _worker_completed_successfully(missing, outcome="", exit_code=0)
    assert not _worker_completed_successfully(failed, outcome="failed", exit_code=0)
