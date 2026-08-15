"""Job definition, state and serialization."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class JobStatus(str, Enum):
    WAITING = "Waiting"
    PREPARING = "Preparing"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    SKIPPED = "Skipped"


#: Allowed transitions, used by the queue manager.
JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.WAITING: {JobStatus.PREPARING, JobStatus.PROCESSING, JobStatus.CANCELLED, JobStatus.SKIPPED},
    JobStatus.PREPARING: {JobStatus.WAITING, JobStatus.PROCESSING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: {JobStatus.WAITING},  # retry
    JobStatus.FAILED: {JobStatus.WAITING},  # retry
    JobStatus.CANCELLED: {JobStatus.WAITING},  # retry
    JobStatus.SKIPPED: {JobStatus.WAITING},
}


def can_transition(from_status: JobStatus, to_status: JobStatus) -> bool:
    return to_status in JOB_TRANSITIONS[from_status]


@dataclass
class Job:
    """A single PDF to process in the queue."""

    input_path: str
    output_path: str = ""
    settings_json: str = ""  # AppSettings snapshot at enqueue time
    pages: list[int] | None = None  # resolved page selection (1-based)
    status: JobStatus = JobStatus.WAITING
    progress_current: int = 0
    progress_total: int = 0
    stage: str = ""
    page_count: int = 0
    file_size: int = 0
    has_text: bool | None = None  # PDF inspection result; None = unknown
    error_message: str = ""
    error_detail: str = ""
    output_sidecar: str = ""
    duration_seconds: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def input(self) -> Path:
        return Path(self.input_path)

    @property
    def output(self) -> Path | None:
        return Path(self.output_path) if self.output_path else None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        values = {k: v for k, v in data.items() if k in known}
        status = values.get("status", JobStatus.WAITING)
        if not isinstance(status, JobStatus):
            try:
                values["status"] = JobStatus(status)
            except (TypeError, ValueError):
                values["status"] = JobStatus.WAITING
        for field_name in ("pages",):
            value = values.get(field_name)
            if value is not None:
                try:
                    values[field_name] = [int(page) for page in value]
                except (TypeError, ValueError):
                    values[field_name] = None
        return cls(**values)

    def set_status(self, status: JobStatus) -> None:
        if not isinstance(status, JobStatus):
            status = JobStatus(status)
        if status is self.status:
            return
        if not can_transition(self.status, status):
            raise ValueError(f"Illegal job transition: {self.status.value} -> {status.value}")
        self.status = status

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.SKIPPED,
        }
