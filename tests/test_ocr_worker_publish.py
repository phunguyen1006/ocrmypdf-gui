from __future__ import annotations

from pathlib import Path

from app.core.ocr_worker import _publish_staged_file


def test_publish_staged_file_falls_back_for_cross_volume_rename(monkeypatch, tmp_path: Path) -> None:
    staged = tmp_path / "work" / "output.pdf"
    final = tmp_path / "drive-g" / "output.pdf"
    staged.parent.mkdir()
    final.parent.mkdir()
    staged.write_bytes(b"finished pdf")

    original_rename = Path.rename

    def simulated_cross_volume_rename(path: Path, target: Path):
        if path == staged:
            raise OSError(17, "The system cannot move the file to a different disk drive")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", simulated_cross_volume_rename)
    _publish_staged_file(staged, final, "job123")

    assert final.read_bytes() == b"finished pdf"
    assert not list(final.parent.glob("*.part"))
