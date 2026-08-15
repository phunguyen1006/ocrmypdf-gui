from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.history_service import HistoryEntry, HistoryService


def test_existing_history_database_is_migrated_with_failure_details(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input TEXT NOT NULL,
                output TEXT DEFAULT '',
                status TEXT NOT NULL,
                pages INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                languages TEXT DEFAULT '',
                mode TEXT DEFAULT '',
                date REAL NOT NULL,
                settings_json TEXT DEFAULT ''
            )
            """
        )

    history = HistoryService(database)
    history.add(
        HistoryEntry(
            input="book.pdf",
            output="",
            status="Failed",
            error_message="Language preparation failed",
            error_detail="offline",
        )
    )

    entry = history.recent(1)[0]
    assert entry.error_message == "Language preparation failed"
    assert entry.error_detail == "offline"
