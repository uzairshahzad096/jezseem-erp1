"""
How a document's reference number is printed.

The old ERP prints a plain numeric reference with the document's year in
front: quotation 1538 dated November 2026 prints as "Invoice # 20261538",
and the supplied Service Invoice for quotation 1 of 2026 carries 20261. The
listings and exports show the stored number (1538) and search works on it,
so only the printout adds the year; the stored number is never rewritten.

References that already carry their date (sales orders and gate passes are
numbered 202609221: 22 September 2026, first of the day) or have a prefix
(SI-000001, LPO-2600006) print exactly as stored.

REQUIRES BUSINESS CONFIRMATION: the calendar year of the document date is
used. For a document dated January–June the financial year's first year
would differ; the old ERP's own printouts from those months settle it.
"""

from datetime import date, datetime


def _is_dated(text: str) -> bool:
    """True when the reference already starts with a YYYYMMDD date."""
    if len(text) < 9:
        return False
    try:
        return 2000 <= datetime.strptime(text[:8], "%Y%m%d").year <= 2099
    except ValueError:
        return False


def printed_reference(number: str | None, on: date | None) -> str:
    text = (number or "").strip()
    if not text.isdigit() or on is None or _is_dated(text):
        return text
    return f"{on.year}{text}"
