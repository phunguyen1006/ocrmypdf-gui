"""Page selection parsing, validation and exclude conversion.

Supported formats (same as OCRmyPDF):
    "1-50,52-100"     - ranges
    "3-end"           - token end = last page
    "2,3,13-17"       - mixing
    "1-5,7-end"       - combining
Also exposes conversion from an exclude list to an equivalent selection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PAGE_TOKEN = re.compile(r"^\s*(\d+)\s*-\s*(end|\d+)\s*$")
_PAGE_SINGLE = re.compile(r"^\s*(\d+)\s*$")


@dataclass(frozen=True)
class PageRange:
    """One validated segment of a page selection."""

    start: int
    end: int


def _parse_segments(spec: str, total: int) -> list[PageRange] | None:
    """Parse 'spec' into sorted, deduplicated, in-range PageRange objects.

    Returns None if the spec is invalid.
    """
    if total < 1 or not spec or not spec.strip():
        return None
    parts = [p.strip() for p in spec.split(",")]
    if any(not p for p in parts):
        return None

    ranges: list[PageRange] = []
    for part in parts:
        try:
            if _PAGE_SINGLE.match(part):
                start = end = int(part.strip())
            elif _PAGE_TOKEN.match(part):
                m = _PAGE_TOKEN.match(part)
                assert m is not None
                start = int(m.group(1))
                end_text = m.group(2)
                end = total if end_text == "end" else int(end_text)
            else:
                return None
        except (AssertionError, ValueError):
            return None
        if start < 1:
            return None
        if end < start:
            return None  # e.g. 52-20
        if end > total:
            return None  # out of bounds
        ranges.append(PageRange(start, end))
    return ranges


def validate_spec(spec: str, total: int) -> str | None:
    """Validate a page selection spec.

    Returns an error message, or None when valid.
    """
    if _parse_segments(spec, total) is None:
        return (
            "Invalid page selection. Use formats like:\n"
            "1-50,52-100 or 3-end or 2,5,9"
        )
    return None


def parse_spec_to_pages(spec: str, total: int) -> list[int] | None:
    """Expand a page selection spec into a sorted list of page numbers."""
    ranges = _parse_segments(spec, total)
    if ranges is None:
        return None
    pages: set[int] = set()
    for r in ranges:
        pages.update(range(r.start, r.end + 1))
    return sorted(pages)


def exclude_to_pages(exclude_spec: str, total: int) -> list[int] | None:
    """'51,124' on a 200 page file -> all pages except 51 and 124."""
    if not exclude_spec.strip():
        return list(range(1, total + 1))
    if validate_spec(exclude_spec, total) is not None:
        return None
    pages = set(parse_spec_to_pages(exclude_spec, total) or [])
    return [p for p in range(1, total + 1) if p not in pages]


def pages_to_spec(pages: list[int], total: int) -> str:
    """Compact representation: [1..50, 52..200] -> '1-50,52-end'."""
    if total < 1:
        return ""
    sorted_pages = sorted({page for page in pages if 1 <= page <= total})
    if not sorted_pages:
        return ""
    segments: list[str] = []
    start = prev = sorted_pages[0]
    for p in sorted_pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        segments.append(_fmt_segment(start, prev, total))
        start = prev = p
    segments.append(_fmt_segment(start, prev, total))
    return ",".join(segments)


def _fmt_segment(start: int, end: int, total: int) -> str:
    if start == end:
        return str(start)
    if end == total:
        return f"{start}-end"
    return f"{start}-{end}"
