from __future__ import annotations

from pathlib import Path

from app.models.settings import AppSettings, SettingsStore


def test_settings_round_trip_and_invalid_values_fall_back() -> None:
    settings = AppSettings.from_dict(
        {
            "ocr_mode": "not-a-mode",
            "optimize": "9",
            "concurrent_files": "99",
            "tesseract_timeout": "-5",
            "rotate_pages": "false",
            "custom_languages": "eng",
        }
    )
    assert settings.ocr_mode == "skip"
    assert settings.optimize == "1"
    assert settings.concurrent_files == 4
    assert settings.tesseract_timeout == 0
    assert settings.rotate_pages is False
    assert settings.custom_languages == ["eng"]


def test_settings_store_persists_json(tmp_path: Path) -> None:
    store = SettingsStore(ini_path=tmp_path / "settings.ini")
    settings = AppSettings(page_range="1-3", sidecar=True)
    store.save(settings)
    loaded = SettingsStore(ini_path=tmp_path / "settings.ini").load()
    assert loaded.page_range == "1-3"
    assert loaded.sidecar is True


def test_auto_language_settings_round_trip() -> None:
    settings = AppSettings.from_dict(
        {
            "language_preset": "auto",
            "auto_download_languages": False,
        }
    )
    restored = AppSettings.from_dict(settings.to_dict())
    assert restored.language_preset == "auto"
    assert restored.auto_download_languages is False


def test_new_settings_default_to_per_page_auto_detect() -> None:
    assert AppSettings().language_preset == "auto"


def test_catalogue_and_combined_language_presets_are_not_reset_to_auto() -> None:
    assert AppSettings.from_dict({"language_preset": "chi_sim"}).language_preset == "chi_sim"
    assert AppSettings.from_dict({"language_preset": "chi_sim+vie"}).language_preset == "chi_sim+vie"
    assert AppSettings.from_dict({"language_preset": "bad language!"}).language_preset == "auto"
