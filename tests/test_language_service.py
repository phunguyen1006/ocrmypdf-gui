from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.language_service import (
    LanguageCatalog,
    LanguageDownloadService,
    LanguageServiceError,
    TesseractDataCache,
    _git_blob_sha1,
)
from app.services.tesseract_service import TesseractLanguageService


def _fake_catalog(tmp_path: Path, payload: bytes) -> LanguageCatalog:
    model_path = "eng.traineddata"
    digest = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
    data = {
        "source": {
            "commit": "test-commit",
            "raw_base": "https://raw.githubusercontent.com/test/repo/test-commit",
            "license": "Apache-2.0",
        },
        "models": [
            {
                "code": "eng",
                "name": "English",
                "kind": "language",
                "script": "",
                "remote_path": model_path,
                "size_bytes": len(payload),
                "checksum": digest,
                "checksum_type": "git-blob-sha1",
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return LanguageCatalog(path)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload)
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


def test_catalogue_is_complete_and_does_not_call_network(monkeypatch) -> None:
    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("catalogue initialization must not call the network")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_network)
    catalog = LanguageCatalog()
    assert len(catalog.models("language")) == 126
    assert len(catalog.models("script")) == 37
    assert catalog.require("vie").name == "Vietnamese"
    assert catalog.source_commit == "87416418657359cb625c412a48b6e1d6d41c29bd"


def test_tesseract_language_service_public_catalog_api(monkeypatch, tmp_path: Path) -> None:
    service = TesseractLanguageService(cache=TesseractDataCache(root=tmp_path / "app-data"))
    assert len(service.catalog()) == 126
    monkeypatch.setattr(service.downloads, "status", lambda code: "Available")
    assert service.status("vie") == "Available"


def test_cache_status_installed_cached_available(tmp_path: Path) -> None:
    catalog = LanguageCatalog()
    cache = TesseractDataCache(root=tmp_path / "app-data")
    cache.system_tessdata_dirs = lambda: []  # type: ignore[method-assign]
    service = LanguageDownloadService(catalog, cache)
    model = catalog.require("eng")
    assert service.status("eng") == "Available"

    cache.model_path(model).parent.mkdir(parents=True, exist_ok=True)
    cache.model_path(model).write_bytes(b"cached")
    assert service.status("eng") == "Cached"

    system = tmp_path / "system-tessdata"
    (system / "eng.traineddata").parent.mkdir(parents=True)
    (system / "eng.traineddata").write_bytes(b"system")
    cache.system_tessdata_dirs = lambda: [system]  # type: ignore[method-assign]
    assert service.status("eng") == "Installed"


def test_download_is_atomic_and_sets_tessdata_prefix(monkeypatch, tmp_path: Path) -> None:
    payload = b"valid language model"
    catalog = _fake_catalog(tmp_path, payload)
    cache = TesseractDataCache(root=tmp_path / "app-data")
    cache.system_tessdata_dirs = lambda: []  # type: ignore[method-assign]
    service = LanguageDownloadService(catalog, cache)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(payload))

    paths = service.ensure_languages(["eng"])
    target = cache.model_path(catalog.require("eng"))
    assert paths == [target]
    assert target.read_bytes() == payload
    assert not Path(str(target) + ".part").exists()
    assert cache.runtime_env()["TESSDATA_PREFIX"] == str(cache.tessdata_dir)
    assert _git_blob_sha1(target) == catalog.require("eng").checksum


def test_download_checksum_mismatch_and_offline_error(monkeypatch, tmp_path: Path) -> None:
    payload = b"valid language model"
    catalog = _fake_catalog(tmp_path, payload)
    cache = TesseractDataCache(root=tmp_path / "app-data")
    cache.system_tessdata_dirs = lambda: []  # type: ignore[method-assign]
    service = LanguageDownloadService(catalog, cache)

    bad_payload = b"x" * len(payload)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(bad_payload))
    with pytest.raises(LanguageServiceError, match="checksum mismatch"):
        service.ensure_languages(["eng"])
    assert not cache.model_path(catalog.require("eng")).exists()

    import urllib.error

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(LanguageServiceError, match="Could not download"):
        service.ensure_languages(["eng"])
