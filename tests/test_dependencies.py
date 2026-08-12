from __future__ import annotations

from app.services import dependency_checker


def test_list_languages_parses_tesseract_output(monkeypatch) -> None:
    class Result:
        stdout = "List of available languages in \"C:\\tessdata\":\neng\nvie\nosd\n"
        stderr = ""

    monkeypatch.setattr(dependency_checker.subprocess, "run", lambda *args, **kwargs: Result())
    assert dependency_checker.list_languages("tesseract.exe") == ["eng", "vie", "osd"]


def test_human_language_name_has_fallback() -> None:
    assert dependency_checker.human_language_name("vie") == "Vietnamese"
    assert dependency_checker.human_language_name("custom") == "custom"
