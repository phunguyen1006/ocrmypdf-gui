"""Offline, page-level language detection for PDF OCR preparation.

The detector never uploads PDF content. Pages are rendered locally at a low
resolution with pypdfium2, a short local Tesseract probe is run, and Lingua
classifies the resulting text when the script is Latin. Only compact
language/page results are stored in the app-data cache; OCR text and images
are removed after each probe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from app.services.tesseract_service import TesseractService
from app.utils.paths import app_data_dir, ensure_app_dirs
from app.utils.processes import CREATE_NO_WINDOW

log = logging.getLogger("app.language_detection")

ProgressCallback = Callable[[int, int, str], None]
REVIEW_CONFIDENCE_THRESHOLD = 0.72
MAX_RASTER_PROBES = 8
MIN_EMBEDDED_TEXT_CHARS = 180


class LanguageDetectionError(RuntimeError):
    """The local renderer or OCR probe could not detect a page."""


class DetectionCancelled(LanguageDetectionError):
    """Detection was cancelled by the user."""


@dataclass(frozen=True)
class PageDetection:
    page: int
    languages: tuple[str, ...]
    confidence: float
    script: str
    candidates: tuple[str, ...] = ()
    cached: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["languages"] = list(self.languages)
        data["candidates"] = list(self.candidates)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PageDetection":
        return cls(
            page=int(data.get("page", 0)),
            languages=tuple(str(value) for value in data.get("languages", []) if str(value)),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            script=str(data.get("script", "")),
            candidates=tuple(str(value) for value in data.get("candidates", []) if str(value)),
            cached=True,
        )


@dataclass(frozen=True)
class DocumentDetection:
    languages: tuple[str, ...]
    confidence: float
    page_results: tuple[PageDetection, ...]
    candidates: tuple[str, ...] = ()

    @property
    def needs_review(self) -> bool:
        return (
            not self.languages
            or bool(self.candidates)
            or self.confidence < REVIEW_CONFIDENCE_THRESHOLD
        )

    def to_dict(self) -> dict:
        return {
            "languages": list(self.languages),
            "confidence": self.confidence,
            "page_results": [page.to_dict() for page in self.page_results],
            "candidates": list(self.candidates),
        }


_VIETNAMESE_MARKS = set("ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")


class LanguageDetectionService:
    """Detect scripts and likely language codes entirely on the local PC."""

    _script_candidates = {
        "latin": ("vie", "eng", "fra", "deu", "spa", "ita", "por"),
        "hans": ("chi_sim",),
        "han simplified": ("chi_sim",),
        "hant": ("chi_tra",),
        "han traditional": ("chi_tra",),
        "han": ("chi_sim", "chi_tra"),
        "hiragana": ("jpn",),
        "katakana": ("jpn",),
        "japanese": ("jpn",),
        "hangul": ("kor",),
        "korean": ("kor",),
        "arabic": ("ara",),
        "cyrillic": ("rus", "ukr", "bul", "srp"),
        "devanagari": ("hin", "mar", "nep"),
        "thai": ("tha",),
        "hebrew": ("heb",),
        "greek": ("ell",),
    }

    def __init__(
        self,
        tesseract: TesseractService | None = None,
        cache_dir: Path | None = None,
        max_raster_probes: int = MAX_RASTER_PROBES,
    ) -> None:
        self.tesseract = tesseract or TesseractService()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else app_data_dir() / "language-detection"
        self._lingua_detector = None
        self._lingua_code_by_language: dict[object, str] = {}
        self._catalog_lingua_code_list: tuple[str, ...] | None = None
        self.max_raster_probes = max(1, int(max_raster_probes))

    def detect_document(
        self,
        pdf_path: Path | str,
        pages: Iterable[int] | None = None,
        *,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> DocumentDetection:
        """Return detected languages, confidence and per-page details.

        ``pages`` uses the same one-based page numbering as the queue. Short
        documents are inspected page by page; long documents use evenly
        distributed representative pages so preparation cannot monopolize the
        queue for several minutes. Results are keyed by the input path, size,
        mtime and page number, so changing the PDF invalidates the local cache.
        """
        path = Path(pdf_path)
        if not path.is_file():
            raise LanguageDetectionError(f"PDF not found: {path}")
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - dependency packaging guard
            raise LanguageDetectionError("pypdfium2 is required for Auto detect.") from exc

        try:
            document = pdfium.PdfDocument(str(path))
            page_count = len(document)
        except Exception as exc:  # noqa: BLE001 - renderer-specific exceptions vary
            raise LanguageDetectionError(f"Could not open PDF for language detection: {exc}") from exc

        selected = sorted({int(page) for page in (pages if pages is not None else range(1, page_count + 1)) if int(page) >= 1})
        selected = [page for page in selected if page <= page_count]
        if not selected:
            return DocumentDetection((), 0.0, ())

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / f"{self._cache_key(path)}.json"
        cached = self._load_cache(cache_path)
        cached_pages = [page for page in selected if str(page) in cached]
        uncached_pages = [page for page in selected if str(page) not in cached]
        pages_to_probe = sorted(set(cached_pages + self._adaptive_probe_pages(uncached_pages)))
        page_results: list[PageDetection] = []
        total = len(pages_to_probe)
        try:
            for index, page_number in enumerate(pages_to_probe, start=1):
                self._check_cancel(cancel_event)
                result = cached.get(str(page_number))
                if result is None:
                    image_path: Path | None = None
                    try:
                        embedded_text = self._extract_embedded_text(document, page_number)
                        if self._has_meaningful_embedded_text(embedded_text):
                            result = self._detect_embedded_text(embedded_text)
                        else:
                            image_path = self._render_page(document, page_number)
                            result = self._detect_page(image_path, cancel_event=cancel_event)
                    finally:
                        if image_path is not None:
                            try:
                                image_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                    result = PageDetection(
                        page=page_number,
                        languages=result.languages,
                        confidence=result.confidence,
                        script=result.script,
                        candidates=result.candidates,
                    )
                    cached[str(page_number)] = result.to_dict()
                page_result = result if isinstance(result, PageDetection) else PageDetection.from_dict(result)
                if page_result.page != page_number:
                    page_result = PageDetection(
                        page=page_number,
                        languages=page_result.languages,
                        confidence=page_result.confidence,
                        script=page_result.script,
                        candidates=page_result.candidates,
                        cached=page_result.cached,
                    )
                page_results.append(page_result)
                if progress is not None:
                    action = "Detecting" if len(selected) <= self.max_raster_probes else "Sampling"
                    progress(index, total, f"{action} page {page_number} of {page_count}")
            self._write_cache(cache_path, cached)
        finally:
            try:
                document.close()
            except Exception:
                pass

        return self._combine(page_results)

    def _adaptive_probe_pages(self, pages: list[int]) -> list[int]:
        """Inspect every short document and representative pages of long ones."""
        if len(pages) <= self.max_raster_probes:
            return list(pages)
        if self.max_raster_probes == 1:
            return [pages[0]]
        last = len(pages) - 1
        indexes = {
            round(index * last / (self.max_raster_probes - 1))
            for index in range(self.max_raster_probes)
        }
        return [pages[index] for index in sorted(indexes)]

    @staticmethod
    def _extract_embedded_text(document, page_number: int) -> str:
        page = None
        text_page = None
        try:
            page = document.get_page(page_number - 1)
            text_page = page.get_textpage()
            return str(text_page.get_text_range() or "")
        except Exception:
            return ""
        finally:
            if text_page is not None:
                try:
                    text_page.close()
                except Exception:
                    pass
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    @staticmethod
    def _has_meaningful_embedded_text(text: str) -> bool:
        without_urls = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
        meaningful = [character for character in without_urls if character.isalpha()]
        return len(meaningful) >= MIN_EMBEDDED_TEXT_CHARS

    def _detect_embedded_text(self, text: str) -> PageDetection:
        probe_codes = ["chi_sim", "chi_tra", "vie", "eng"]
        languages, confidence, candidates = self._infer_languages(text, "", probe_codes)
        script = "han" if _CJK_RE.search(text) else ("latin" if _LATIN_RE.search(text) else "")
        return PageDetection(0, tuple(languages), confidence, script, tuple(candidates))

    def _render_page(self, document, page_number: int) -> Path:
        try:
            page = document.get_page(page_number - 1)
            bitmap = page.render(scale=1.0, rotation=0)
            image = bitmap.to_pil().convert("RGB")
            ensure_app_dirs()
            handle = tempfile.NamedTemporaryFile(prefix="language-probe-", suffix=".png", dir=app_data_dir() / "tmp", delete=False)
            image.save(handle, format="PNG", optimize=True)
            handle.close()
            try:
                page.close()
            except Exception:
                pass
            try:
                bitmap.close()
            except Exception:
                pass
            return Path(handle.name)
        except Exception as exc:  # noqa: BLE001
            raise LanguageDetectionError(f"Could not render a PDF page: {exc}") from exc

    def _detect_page(self, image_path: Path, *, cancel_event: Event | None = None) -> PageDetection:
        exe = self.tesseract.tesseract_path()
        if not exe:
            raise LanguageDetectionError(
                "Tesseract was not found. Install Tesseract before using Auto detect."
            )

        available = set(self.tesseract.languages())
        # A single multilingual OCR pass handles the common CJK/Latin case.
        # OSD is only needed when that pass is inconclusive, cutting the
        # normal Auto detect cost roughly in half.
        probe_codes = [code for code in ("chi_sim", "chi_tra", "vie", "eng") if code in available]
        if not probe_codes:
            probe_codes = sorted(code for code in available if code != "osd")[:3]
        if not probe_codes:
            raise LanguageDetectionError("No Tesseract language model is available for the detection probe.")

        text = self._ocr_probe(exe, image_path, probe_codes, cancel_event=cancel_event)
        inferred_script = "han" if _CJK_RE.search(text) else ("latin" if _LATIN_RE.search(text) else "")
        languages, confidence, candidates = self._infer_languages(text, inferred_script, probe_codes)
        script = inferred_script
        script_confidence = 0.0
        if not languages or confidence < REVIEW_CONFIDENCE_THRESHOLD:
            script, script_confidence = self._detect_script(exe, image_path, cancel_event=cancel_event)
            if script_confidence < 30.0:
                script = inferred_script
            languages, confidence, candidates = self._infer_languages(text, script, probe_codes)
        if not languages and script and script_confidence >= 30.0:
            script_candidates = [code for code in self._script_candidates_for(script) if self.tesseract.catalog_model(code)]
            if len(script_candidates) == 1:
                languages = script_candidates
                confidence = max(confidence, min(script_confidence / 100.0, 1.0))
            elif script_candidates:
                candidates = list(dict.fromkeys(candidates + script_candidates))
        if script_confidence > 0 and confidence == 0:
            confidence = min(script_confidence / 100.0, 1.0)
        return PageDetection(
            page=0,
            languages=tuple(languages),
            confidence=max(0.0, min(float(confidence), 1.0)),
            script=script,
            candidates=tuple(candidates),
        )

    def _detect_script(
        self,
        exe: str,
        image_path: Path,
        *,
        cancel_event: Event | None = None,
    ) -> tuple[str, float]:
        if "osd" not in set(self.tesseract.languages()):
            return "", 0.0
        try:
            output = self._run_tesseract(exe, image_path, "osd", psm="0", cancel_event=cancel_event)
        except LanguageDetectionError:
            # OSD legitimately fails on very short or low-resolution pages.
            # The multilingual probe below remains useful and does not need
            # a console window, so treat OSD failure as an unknown script.
            return "", 0.0
        script_match = re.search(r"^Script:\s*(.+)$", output, re.MULTILINE | re.IGNORECASE)
        confidence_match = re.search(r"^Script confidence:\s*([0-9.]+)", output, re.MULTILINE | re.IGNORECASE)
        script = script_match.group(1).strip().lower() if script_match else ""
        confidence = float(confidence_match.group(1)) if confidence_match else 0.0
        return script, confidence

    def _ocr_probe(
        self,
        exe: str,
        image_path: Path,
        codes: list[str],
        *,
        cancel_event: Event | None = None,
    ) -> str:
        return self._run_tesseract(
            exe,
            image_path,
            "+".join(codes),
            psm="6",
            cancel_event=cancel_event,
        )

    def _run_tesseract(
        self,
        exe: str,
        image_path: Path,
        languages: str,
        *,
        psm: str,
        cancel_event: Event | None = None,
    ) -> str:
        process = None
        try:
            # Ask Tesseract to write its renderer output to a private file.
            # This avoids anonymous/inheritable stdio handles, which can fail
            # under sandboxed Windows sessions (WinError 6/50), and cannot
            # deadlock if Tesseract emits a large amount of text.
            with tempfile.TemporaryDirectory(prefix="language-result-") as result_dir:
                output_base = Path(result_dir) / "probe"
                command = [exe, str(image_path), str(output_base), "--psm", psm, "-l", languages]
                process = subprocess.Popen(
                    command,
                    env=self.tesseract.runtime_env(),
                    creationflags=CREATE_NO_WINDOW,
                )
                deadline = time.monotonic() + 30.0
                while True:
                    self._check_cancel(cancel_event)
                    try:
                        process.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            process.kill()
                            process.wait()
                            raise LanguageDetectionError("Tesseract language detection timed out after 30 seconds.")
                        continue
                output = ""
                for result_path in (output_base.with_suffix(".txt"), output_base.with_suffix(".osd")):
                    if result_path.is_file():
                        output += result_path.read_text(encoding="utf-8", errors="replace") + "\n"
        except DetectionCancelled:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise LanguageDetectionError(f"Tesseract detection probe failed: {exc}") from exc
        if process.returncode != 0 and not output.strip():
            raise LanguageDetectionError("Tesseract returned no language detection result.")
        return output

    def _infer_languages(self, text: str, script: str, probe_codes: list[str]) -> tuple[list[str], float, list[str]]:
        clean = text.strip()
        cjk_count = len(_CJK_RE.findall(clean))
        latin_count = len(_LATIN_RE.findall(clean))
        languages: list[str] = []
        candidates: list[str] = []
        confidence = 0.0

        script_key = script.lower().strip()
        japanese_script = any(marker in script_key for marker in ("japanese", "hiragana", "katakana"))
        if japanese_script:
            if "jpn" in probe_codes or self.tesseract.catalog_model("jpn"):
                languages.append("jpn")
                confidence = 0.78
        elif cjk_count:
            variant = self._infer_cjk_variant(clean)
            if "hant" in script_key or "traditional" in script_key or variant == "chi_tra":
                languages.append("chi_tra")
            elif "hans" in script_key or "simplified" in script_key or variant == "chi_sim":
                languages.append("chi_sim")
            else:
                candidates.extend(["chi_sim", "chi_tra"])

        if latin_count or not cjk_count:
            # Keep the OCR probe small and fast, but let Lingua classify
            # against every compatible language in the bundled catalogue.
            # This is what allows Auto detect to return e.g. ``fra`` even
            # before French tessdata has been downloaded.
            vietnamese_marks = sum(character in _VIETNAMESE_MARKS for character in clean)
            if vietnamese_marks >= 2 and "vie" in probe_codes:
                languages.append("vie")
                confidence = max(confidence, min(0.82 + vietnamese_marks * 0.01, 0.95))
            # Classifying a mixed Han/Latin OCR transcript as one block makes
            # Lingua mistake Chinese vocabulary for Japanese and short lesson
            # labels for unrelated Latin languages.  Vietnamese diacritics are
            # stronger direct evidence than that statistical guess.  For other
            # pages, remove CJK before classifying the Latin portion.
            lingua_text = _CJK_RE.sub(" ", clean) if cjk_count else clean
            lingua_codes = list(self._catalog_lingua_codes())
            scores = {} if vietnamese_marks >= 2 else self._language_scores(lingua_text, lingua_codes)
            if scores:
                ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
                top_code, top_score = ranked[0]
                second_score = ranked[1][1] if len(ranked) > 1 else 0.0
                confidence = float(top_score)
                if top_code not in languages and top_score >= 0.62:
                    languages.append(top_code)
                if vietnamese_marks >= 2 and top_code == "eng" and "vie" in probe_codes:
                    languages.append("vie")
                if top_score < 0.62 or top_score - second_score < 0.12:
                    candidates.extend(code for code, _score in ranked[:3])
            else:
                confidence = max(confidence, 0.0)
            if not languages and "latin" in script_key and len(probe_codes) == 1:
                languages.append(probe_codes[0])
        else:
            confidence = 0.78 if languages else 0.0

        # A page containing both CJK and Vietnamese marks is explicitly mixed;
        # preserve both codes instead of letting the dominant script win.
        if cjk_count and sum(character in _VIETNAMESE_MARKS for character in clean) >= 2 and "vie" in probe_codes:
            languages.append("vie")

        ordered_languages = list(dict.fromkeys(code for code in languages if code))
        return ordered_languages, confidence, candidates if candidates else ([] if ordered_languages else probe_codes)

    @staticmethod
    def _infer_cjk_variant(text: str) -> str | None:
        """Use common script-specific characters as a local fallback to OSD."""
        simplified = set("这 个 个 中 国 华 测 试 页 面 现 实 开 发 语 言 书 学 习 课 号 们 说 过 发 现".split())
        traditional = set("這 個 中 國 華 測 試 頁 面 現 實 開 發 語 言 書 學 習 課 號 們 說 過 發 現".split())
        simplified_score = sum(character in simplified for character in text)
        traditional_score = sum(character in traditional for character in text)
        if simplified_score > traditional_score:
            return "chi_sim"
        if traditional_score > simplified_score:
            return "chi_tra"
        return None

    def _language_scores(self, text: str, codes: list[str]) -> dict[str, float]:
        if not text or not codes:
            return {}
        detector = self._get_lingua_detector(codes)
        if detector is None:
            return {}
        try:
            values = detector.compute_language_confidence_values(text)
        except Exception:
            return {}
        scores: dict[str, float] = {}
        for value in values:
            code = self._lingua_code_by_language.get(value.language)
            if code:
                scores[code] = float(value.value)
        return scores

    def _catalog_lingua_codes(self) -> tuple[str, ...]:
        if self._catalog_lingua_code_list is not None:
            return self._catalog_lingua_code_list
        try:
            from lingua import Language
        except ImportError:  # pragma: no cover - dependency packaging guard
            self._catalog_lingua_code_list = ()
            return self._catalog_lingua_code_list
        supported = {language.iso_code_639_3.name.lower() for language in Language.all()}
        codes: list[str] = []
        for model in self.tesseract.catalog_models():
            if not model.is_language:
                continue
            # CJK languages are resolved by script/character heuristics.
            # Feeding Han text to Lingua can confuse Chinese and Japanese, and
            # Lingua cannot distinguish Simplified from Traditional Chinese.
            if model.code in {"chi_sim", "chi_tra", "jpn", "kor"}:
                continue
            iso3 = {"chi_sim": "zho", "chi_tra": "zho"}.get(model.code, model.code)
            if iso3 in supported:
                codes.append(model.code)
        self._catalog_lingua_code_list = tuple(dict.fromkeys(codes))
        return self._catalog_lingua_code_list

    def _get_lingua_detector(self, codes: list[str]):
        try:
            from lingua import Language, LanguageDetectorBuilder
        except ImportError:  # pragma: no cover - dependency packaging guard
            return None
        languages = []
        code_by_language: dict[object, str] = {}
        all_languages = Language.all()
        for code in dict.fromkeys(codes):
            iso3 = {"chi_sim": "zho", "chi_tra": "zho"}.get(code, code)
            for language in all_languages:
                if language.iso_code_639_3.name.lower() == iso3.lower():
                    languages.append(language)
                    code_by_language[language] = code
                    break
        if not languages:
            return None
        key = "+".join(sorted(code_by_language.values()))
        if getattr(self, "_lingua_key", "") != key:
            self._lingua_detector = LanguageDetectorBuilder.from_languages(*languages).with_preloaded_language_models().build()
            self._lingua_code_by_language = code_by_language
            self._lingua_key = key
        return self._lingua_detector

    def _script_candidates_for(self, script: str) -> tuple[str, ...]:
        key = script.lower().strip()
        for marker, codes in self._script_candidates.items():
            if marker in key:
                return codes
        return self._script_candidates["latin"]

    @staticmethod
    def _check_cancel(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise DetectionCancelled("Language detection cancelled.")

    @staticmethod
    def _cache_key(path: Path) -> str:
        stat = path.stat()
        value = f"v3|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _load_cache(path: Path) -> dict[str, dict]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_cache(path: Path, data: dict[str, dict]) -> None:
        temporary = Path(str(path) + ".part")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _combine(page_results: list[PageDetection]) -> DocumentDetection:
        languages = list(dict.fromkeys(code for page in page_results for code in page.languages))
        candidates = list(dict.fromkeys(code for page in page_results for code in page.candidates))
        simplified_votes = sum("chi_sim" in page.languages for page in page_results)
        traditional_votes = sum("chi_tra" in page.languages for page in page_results)
        if simplified_votes > traditional_votes:
            languages = [code for code in languages if code != "chi_tra"]
            candidates = [code for code in candidates if code not in {"chi_sim", "chi_tra"}]
        elif traditional_votes > simplified_votes:
            languages = [code for code in languages if code != "chi_sim"]
            candidates = [code for code in candidates if code not in {"chi_sim", "chi_tra"}]
        confidence = min((page.confidence for page in page_results), default=0.0)
        return DocumentDetection(tuple(languages), confidence, tuple(page_results), tuple(candidates))
