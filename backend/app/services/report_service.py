"""
Report service — PDF filename generation helpers.

The PDF download filename is derived from the engagement name by replacing
every non-alphanumeric character (including spaces) with a hyphen, truncating
the resulting name portion to at most 50 characters, and appending
``-report-YYYY-MM-DD.pdf`` using the supplied date.

Example
-------
    >>> from datetime import date
    >>> generate_report_filename("internal pentest!", date(2026, 6, 3))
    'internal-pentest--report-2026-06-03.pdf'

Requirements: 9.4
"""

from __future__ import annotations

import re
from datetime import date

# Matches any character that is NOT a letter (a-z, A-Z) or digit (0-9).
_NON_ALPHANUMERIC: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9]")

# Maximum length of the name portion of the filename (before the suffix).
_MAX_NAME_LENGTH: int = 50


def generate_report_filename(name: str, report_date: date) -> str:
    """Return a PDF download filename derived from *name* and *report_date*.

    Processing steps (applied in order):

    1. Replace every non-alphanumeric character (including spaces, punctuation,
       and Unicode) with a hyphen.
    2. Truncate the resulting string to at most :data:`_MAX_NAME_LENGTH`
       characters (50).
    3. Append ``-report-YYYY-MM-DD.pdf`` using *report_date*.

    Parameters
    ----------
    name:
        The engagement name string.  May contain arbitrary characters.
    report_date:
        The date to embed in the filename suffix.

    Returns
    -------
    str
        A filename of the form ``<sanitised-name>-report-YYYY-MM-DD.pdf``
        where ``<sanitised-name>`` is at most 50 characters long.

    Examples
    --------
    >>> from datetime import date
    >>> generate_report_filename("internal pentest!", date(2026, 6, 3))
    'internal-pentest--report-2026-06-03.pdf'
    >>> generate_report_filename("Q1 2026 Corp Pentest", date(2026, 6, 3))
    'Q1-2026-Corp-Pentest-report-2026-06-03.pdf'
    """
    # Step 1: replace non-alphanumeric characters with hyphens.
    sanitised = _NON_ALPHANUMERIC.sub("-", name)

    # Step 2: truncate to at most 50 characters.
    truncated = sanitised[:_MAX_NAME_LENGTH]

    # Step 3: append the fixed suffix with the formatted date.
    date_str = report_date.strftime("%Y-%m-%d")
    return f"{truncated}-report-{date_str}.pdf"
