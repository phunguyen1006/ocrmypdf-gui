from __future__ import annotations

import json

import pytest

from app.models.job import Job, JobStatus


def test_job_state_machine_allows_retry_from_terminal_state() -> None:
    job = Job("scan.pdf")
    job.set_status(JobStatus.PROCESSING)
    job.set_status(JobStatus.FAILED)
    job.set_status(JobStatus.WAITING)
    assert job.status is JobStatus.WAITING


def test_job_state_machine_rejects_skipping_processing() -> None:
    job = Job("scan.pdf")
    with pytest.raises(ValueError):
        job.set_status(JobStatus.COMPLETED)


def test_job_json_round_trip_restores_enum_and_pages() -> None:
    original = Job("scan.pdf", pages=[1, 3], status=JobStatus.CANCELLED)
    restored = Job.from_dict(json.loads(original.to_json()))
    assert restored.status is JobStatus.CANCELLED
    assert restored.pages == [1, 3]


def test_job_preparation_is_visible_and_can_return_to_waiting() -> None:
    job = Job("scan.pdf")
    job.set_status(JobStatus.PREPARING)
    job.set_status(JobStatus.WAITING)
    assert job.status is JobStatus.WAITING
