from __future__ import annotations

import subprocess

from app.utils.processes import CREATE_NO_WINDOW, add_hidden_console_flag


def test_add_hidden_console_flag_preserves_existing_windows_flags(monkeypatch) -> None:
    monkeypatch.setattr("app.utils.processes.sys.platform", "win32")
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

    result = add_hidden_console_flag(kwargs)

    assert result is kwargs
    assert result["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert result["creationflags"] & CREATE_NO_WINDOW


def test_add_hidden_console_flag_is_noop_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr("app.utils.processes.sys.platform", "linux")
    kwargs = {}

    assert add_hidden_console_flag(kwargs) == {}
