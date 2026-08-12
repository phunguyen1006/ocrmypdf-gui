from __future__ import annotations

from app.core.page_ranges import (
    exclude_to_pages,
    pages_to_spec,
    parse_spec_to_pages,
    validate_spec,
)


def test_parse_mixed_ranges_and_end() -> None:
    assert parse_spec_to_pages("1-2,4,6-end", 7) == [1, 2, 4, 6, 7]


def test_invalid_ranges_are_rejected() -> None:
    for spec in ("1--50", "abc", "52-20", "0", "1-9"):
        assert validate_spec(spec, 8) is not None
        assert parse_spec_to_pages(spec, 8) is None


def test_exclude_pages_and_compaction() -> None:
    pages = exclude_to_pages("2,4-5", 7)
    assert pages == [1, 3, 6, 7]
    assert pages_to_spec(pages, 7) == "1,3,6-end"


def test_pages_to_spec_deduplicates_and_ignores_out_of_range() -> None:
    assert pages_to_spec([0, 1, 1, 2, 3, 9], 3) == "1-end"
    assert pages_to_spec([], 3) == ""
