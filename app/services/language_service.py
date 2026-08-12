"""Offline catalogue, app-private tessdata cache and lazy downloads."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from app.utils.paths import app_data_dir
from app.utils.resources import resource_path

log = logging.getLogger("app.languages")

ProgressCallback = Callable[[str, int, int], None]


class LanguageServiceError(RuntimeError):
    """A language catalogue/cache/download operation failed."""


class DownloadCancelled(LanguageServiceError):
    """A language download was cancelled by the user."""


@dataclass(frozen=True)
class LanguageModel:
    code: str
    name: str
    kind: str
    script: str
    remote_path: str
    size_bytes: int
    checksum: str
    checksum_type: str

    @property
    def is_language(self) -> bool:
        return self.kind == "language"


class LanguageCatalog:
    """Load the bundled catalogue without making a network request."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or resource_path("app/data/tesseract_languages.json")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LanguageServiceError(f"Could not read the bundled language catalogue: {exc}") from exc
        source = raw.get("source") or {}
        self.source_commit = str(source.get("commit", ""))
        self.raw_base = str(source.get("raw_base", "")).rstrip("/")
        self.license = str(source.get("license", ""))
        self._models = tuple(
            LanguageModel(
                code=str(item["code"]),
                name=str(item.get("name") or item["code"]),
                kind=str(item.get("kind", "language")),
                script=str(item.get("script", "")),
                remote_path=str(item["remote_path"]),
                size_bytes=int(item.get("size_bytes", 0) or 0),
                checksum=str(item.get("checksum", "")),
                checksum_type=str(item.get("checksum_type", "")),
            )
            for item in raw.get("models", [])
        )
        self._by_code = {model.code: model for model in self._models}

    def models(self, kind: str | None = "language") -> list[LanguageModel]:
        if kind is None:
            return list(self._models)
        return [model for model in self._models if model.kind == kind]

    def get(self, code: str) -> LanguageModel | None:
        return self._by_code.get(code)

    def require(self, code: str) -> LanguageModel:
        model = self.get(code)
        if model is None:
            raise LanguageServiceError(f"Language model is not in the bundled catalogue: {code}")
        return model


def _git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()  # noqa: S324 - Git blob compatibility checksum
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TesseractDataCache:
    """Maintain a writable merged tessdata tree in the user data directory."""

    def __init__(self, tesseract_exe: str | None = None, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else app_data_dir()
        self.tessdata_dir = self.root / "tessdata"
        self.tesseract_exe = tesseract_exe

    def ensure_dirs(self) -> None:
        self.tessdata_dir.mkdir(parents=True, exist_ok=True)

    def system_tessdata_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        prefix = os.environ.get("TESSDATA_PREFIX", "").strip()
        if prefix:
            prefix_path = Path(prefix)
            candidates.append(prefix_path if prefix_path.name.lower() == "tessdata" else prefix_path / "tessdata")
        if self.tesseract_exe:
            exe_path = Path(self.tesseract_exe)
            candidates.append(exe_path.parent / "tessdata")
        candidates.extend(
            [
                Path("C:/Program Files/Tesseract-OCR/tessdata"),
                Path("C:/Program Files (x86)/Tesseract-OCR/tessdata"),
            ]
        )
        unique: list[Path] = []
        seen: set[str] = set()
        cache_key = os.path.normcase(os.path.abspath(str(self.tessdata_dir)))
        for candidate in candidates:
            key = os.path.normcase(os.path.abspath(str(candidate)))
            if key != cache_key and key not in seen and candidate.is_dir():
                seen.add(key)
                unique.append(candidate)
        return unique

    def system_model_path(self, model: LanguageModel) -> Path | None:
        relative = Path(model.remote_path)
        for base in self.system_tessdata_dirs():
            candidate = base / relative
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        return None

    def model_path(self, model: LanguageModel) -> Path:
        return self.tessdata_dir / model.remote_path

    def is_cached(self, model: LanguageModel) -> bool:
        path = self.model_path(model)
        return path.is_file() and path.stat().st_size > 0

    def status(self, model: LanguageModel) -> str:
        if self.system_model_path(model) is not None:
            return "Installed"
        if self.is_cached(model):
            return "Cached"
        return "Available"

    def sync_system_models(self) -> None:
        """Copy system models into the merged cache without overwriting downloads."""
        self.ensure_dirs()
        for source_root in self.system_tessdata_dirs():
            for source in source_root.rglob("*.traineddata"):
                relative = source.relative_to(source_root)
                destination = self.tessdata_dir / relative
                if destination.exists():
                    continue
                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                except OSError as exc:
                    log.debug("Could not copy system tessdata %s: %s", source, exc)
            for folder_name in ("configs", "tessconfigs"):
                source_folder = source_root / folder_name
                if not source_folder.is_dir():
                    continue
                destination_folder = self.tessdata_dir / folder_name
                for source in source_folder.rglob("*"):
                    if not source.is_file():
                        continue
                    destination = destination_folder / source.relative_to(source_folder)
                    if destination.exists():
                        continue
                    try:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                    except OSError as exc:
                        log.debug("Could not copy Tesseract config %s: %s", source, exc)

    def runtime_env(self) -> dict[str, str]:
        self.ensure_dirs()
        self.sync_system_models()
        env = os.environ.copy()
        # Tesseract treats TESSDATA_PREFIX as the directory containing the
        # .traineddata files. Pointing it at the parent app-data directory
        # makes --list-langs return "tessdata/eng", which OCRmyPDF rejects.
        env["TESSDATA_PREFIX"] = str(self.tessdata_dir)
        return env


class LanguageDownloadService:
    """Download pinned models into the app-private cache."""

    def __init__(self, catalog: LanguageCatalog | None = None, cache: TesseractDataCache | None = None) -> None:
        self.catalog = catalog or LanguageCatalog()
        self.cache = cache or TesseractDataCache()

    def status(self, code: str) -> str:
        return self.cache.status(self.catalog.require(code))

    def ensure_languages(
        self,
        codes: Iterable[str],
        *,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        self.cache.ensure_dirs()
        self.cache.sync_system_models()
        for code in codes:
            code = str(code).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            model = self.catalog.require(code)
            path = self.cache.model_path(model)
            if self.cache.is_cached(model):
                if self._validate_file(model, path):
                    paths.append(path)
                    continue
                log.warning("Ignoring invalid cached tessdata file: %s", path)
                try:
                    path.unlink()
                except OSError:
                    pass
            system_path = self.cache.system_model_path(model)
            if system_path is not None:
                if not path.exists():
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(system_path, path)
                    except OSError:
                        # The runtime prefix will still be able to use the
                        # original system file if the user cache is read-only.
                        paths.append(system_path)
                        continue
                paths.append(path)
                continue
            self._download(model, cancel_event=cancel_event, progress=progress)
            paths.append(path)
        return paths

    def _download(
        self,
        model: LanguageModel,
        *,
        cancel_event: Event | None,
        progress: ProgressCallback | None,
    ) -> None:
        if not self.catalog.raw_base.startswith("https://raw.githubusercontent.com/"):
            raise LanguageServiceError("The language catalogue has an untrusted download source.")
        target = self.cache.model_path(model)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = Path(str(target) + ".part")
        url = f"{self.catalog.raw_base}/{urllib.parse.quote(model.remote_path, safe='/')}"
        request = urllib.request.Request(url, headers={"User-Agent": "OCRmyPDF-GUI/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - allowlisted HTTPS host
                total = int(response.headers.get("Content-Length", model.size_bytes or 0) or 0)
                received = 0
                with part.open("wb") as stream:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise DownloadCancelled(f"Download cancelled: {model.name}")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        stream.write(chunk)
                        received += len(chunk)
                        if progress is not None:
                            progress(model.code, received, total)
            if model.size_bytes and part.stat().st_size != model.size_bytes:
                raise LanguageServiceError(f"Downloaded size mismatch for {model.name}.")
            if model.checksum and model.checksum_type == "git-blob-sha1":
                actual = _git_blob_sha1(part)
                if actual != model.checksum:
                    raise LanguageServiceError(f"Downloaded checksum mismatch for {model.name}.")
            part.replace(target)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise LanguageServiceError(f"Could not download {model.name}: {exc}") from exc
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass

    @staticmethod
    def _validate_file(model: LanguageModel, path: Path) -> bool:
        try:
            if model.size_bytes and path.stat().st_size != model.size_bytes:
                return False
            if model.checksum and model.checksum_type == "git-blob-sha1":
                return _git_blob_sha1(path) == model.checksum
            return path.stat().st_size > 0
        except OSError:
            return False
