"""
Unit tests for the PDF report filename helper.

Tests cover: special characters, spaces, Unicode, max-length names,
boundary values, and the documented example from requirement 9.4.

Requirements: 9.4
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.report_service import (
    _MAX_NAME_LENGTH,
    generate_report_filename,
)


class TestGenerateReportFilename:
    """Unit tests for generate_report_filename."""

    def test_documented_example(self) -> None:
        """Requirement 9.4 example: 'internal pentest!' → 'internal-pentest--report-2026-06-03.pdf'."""
        result = generate_report_filename("internal pentest!", date(2026, 6, 3))
        assert result == "internal-pentest--report-2026-06-03.pdf"

    def test_spaces_replaced_with_hyphens(self) -> None:
        result = generate_report_filename("hello world", date(2026, 1, 1))
        assert result == "hello-world-report-2026-01-01.pdf"

    def test_alphanumeric_name_unchanged(self) -> None:
        result = generate_report_filename("Pentest2026", date(2026, 6, 3))
        assert result == "Pentest2026-report-2026-06-03.pdf"

    def test_punctuation_replaced_with_hyphens(self) -> None:
        result = generate_report_filename("Q1/2026: Corp!", date(2026, 6, 3))
        assert result == "Q1-2026--Corp--report-2026-06-03.pdf"

    def test_name_truncated_to_50_chars(self) -> None:
        long_name = "a" * 60  # 60 alphanumeric chars → sanitised stays 60, truncate to 50
        result = generate_report_filename(long_name, date(2026, 6, 3))
        name_part = result.replace("-report-2026-06-03.pdf", "")
        assert len(name_part) == _MAX_NAME_LENGTH
        assert result == "a" * 50 + "-report-2026-06-03.pdf"

    def test_name_exactly_50_chars_not_truncated(self) -> None:
        name = "a" * 50
        result = generate_report_filename(name, date(2026, 6, 3))
        name_part = result.replace("-report-2026-06-03.pdf", "")
        assert len(name_part) == 50

    def test_name_51_chars_truncated_to_50(self) -> None:
        name = "a" * 51
        result = generate_report_filename(name, date(2026, 6, 3))
        name_part = result.replace("-report-2026-06-03.pdf", "")
        assert len(name_part) == 50

    def test_empty_name(self) -> None:
        result = generate_report_filename("", date(2026, 1, 1))
        assert result == "-report-2026-01-01.pdf"

    def test_date_format_is_iso(self) -> None:
        result = generate_report_filename("test", date(2025, 12, 31))
        assert result.endswith("-report-2025-12-31.pdf")

    def test_unicode_chars_replaced_with_hyphens(self) -> None:
        # Unicode characters are non-alphanumeric (ASCII sense) and must become hyphens.
        result = generate_report_filename("résumé café", date(2026, 6, 3))
        # 'r', 's', 'm' are kept; 'é', space, 'c', 'f', 'é' → hyphens where non-ASCII
        assert result.endswith("-report-2026-06-03.pdf")
        name_part = result.replace("-report-2026-06-03.pdf", "")
        # Name part must only contain [a-zA-Z0-9-]
        import re
        assert re.fullmatch(r"[a-zA-Z0-9\-]*", name_part), (
            f"Name part contains unexpected characters: {name_part!r}"
        )

    def test_truncation_happens_before_suffix(self) -> None:
        """Truncation must happen before appending the suffix, not after."""
        # A name of 55 chars should result in a name part of exactly 50 chars.
        name = "x" * 55
        result = generate_report_filename(name, date(2026, 6, 3))
        assert result == "x" * 50 + "-report-2026-06-03.pdf"
        # The suffix is NOT part of the 50-char budget.
        assert len(result) == 50 + len("-report-2026-06-03.pdf")

    def test_only_special_chars(self) -> None:
        # "!!!---###" is 9 characters, each non-alphanumeric → 9 hyphens.
        result = generate_report_filename("!!!---###", date(2026, 6, 3))
        assert result == "----------report-2026-06-03.pdf"

    def test_mixed_case_preserved(self) -> None:
        result = generate_report_filename("InternalPENTEST", date(2026, 6, 3))
        assert result == "InternalPENTEST-report-2026-06-03.pdf"
