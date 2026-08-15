"""History of processed jobs, stored in SQLite (user data dir)."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.paths import app_data_dir


@dataclass
class HistoryEntry:
    input: str
    output: str
    status: str
    pages: int = 0
    duration_seconds: float = 0.0
    languages: str = ""
    mode: str = ""
    date: float = field(default_factory=time.time)
    settings_json: str = ""
    error_message: str = ""
    error_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "input": self.input,
            "output": self.output,
            "status": self.status,
            "pages": self.pages,
            "duration_seconds": self.duration_seconds,
            "languages": self.languages,
            "mode": self.mode,
            "date": self.date,
            "settings_json": self.settings_json,
            "error_message": self.error_message,
            "error_detail": self.error_detail,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    status TEXT NOT NULL,
    pages INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    languages TEXT DEFAULT '',
    mode TEXT DEFAULT '',
    date REAL NOT NULL,
    settings_json TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    error_detail TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_history_date ON history(date DESC);
"""


class HistoryService:
    """Thread-light SQLite store. Each call opens a short-lived connection."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = app_data_dir() / "history.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
            for name in ("error_message", "error_detail"):
                if name not in columns:
                    conn.execute(f"ALTER TABLE history ADD COLUMN {name} TEXT DEFAULT ''")

    def add(self, entry: HistoryEntry) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO history (input, output, status, pages, duration_seconds,"
                " languages, mode, date, settings_json, error_message, error_detail)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry.input,
                    entry.output,
                    entry.status,
                    entry.pages,
                    entry.duration_seconds,
                    entry.languages,
                    entry.mode,
                    entry.date,
                    entry.settings_json,
                    entry.error_message,
                    entry.error_detail,
                ),
            )

    def recent(self, limit: int = 100) -> list[HistoryEntry]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT input, output, status, pages, duration_seconds, languages, mode, date, settings_json,"
                " error_message, error_detail"
                " FROM history ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [HistoryEntry(*row) for row in rows]

    def remove(self, entry: HistoryEntry) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM history WHERE input = ? AND output = ? AND date = ?",
                (entry.input, entry.output, entry.date),
            )

    def clear(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM history")

    def from_job(self, job) -> HistoryEntry:
        settings = {}
        if job.settings_json:
            try:
                settings = json.loads(job.settings_json)
            except json.JSONDecodeError:
                pass
        langs = settings.get("language_preset", "")
        if langs == "custom":
            langs = "+".join(settings.get("custom_languages", []))
        return HistoryEntry(
            input=job.input_path,
            output=job.output_path,
            status=job.status.value,
            pages=job.page_count,
            duration_seconds=job.duration_seconds,
            languages=langs,
            mode=settings.get("ocr_mode", ""),
            settings_json=job.settings_json,
            error_message=job.error_message,
            error_detail=job.error_detail,
        )
