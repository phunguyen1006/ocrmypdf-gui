from __future__ import annotations

from pathlib import Path

from app.utils.paths import output_name_for, unique_output_path


def test_unicode_output_name_preserves_stem_and_suffix() -> None:
    source = Path("Giáo trình CNXHKH (bản cũ).pdf")
    assert output_name_for(source) == "Giáo trình CNXHKH (bản cũ) (OCR).pdf"


def test_unique_output_path_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"input")
    first = tmp_path / "scan (OCR).pdf"
    second = tmp_path / "scan (OCR 2).pdf"
    first.write_bytes(b"existing")
    second.write_bytes(b"existing")

    assert unique_output_path(source) == tmp_path / "scan (OCR 3).pdf"


def test_unique_output_path_respects_reserved_queue_outputs(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    reserved = tmp_path / "scan (OCR).pdf"

    assert unique_output_path(source, reserved_paths=[reserved]) == tmp_path / "scan (OCR 2).pdf"
