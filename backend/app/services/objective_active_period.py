"""Shared active-period rule for monthly objectives.

There is no holiday registry in the application today.  ``holiday_dates`` is
therefore an optional dependency point for a future configured calendar; it is
never populated with an arbitrary country-specific list.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime, timedelta


def application_local_date() -> date:
    """Return today's date in the server's configured local timezone."""
    return datetime.now().astimezone().date()


def calculate_active_period(
    reference_date: date | None = None,
    holiday_dates: Collection[date] | None = None,
) -> tuple[date, date]:
    """Return ``(today, third business day from today)``.

    The reference date is always the start of the period, even when it is a
    weekend or holiday.  It only contributes to the three-day count when it is
    a weekday and not listed as a holiday.
    """
    active_from = reference_date or application_local_date()
    holidays = set(holiday_dates or ())
    candidate = active_from
    business_days = 0
    while business_days < 3:
        if candidate.weekday() < 5 and candidate not in holidays:
            business_days += 1
        if business_days == 3:
            return active_from, candidate
        candidate += timedelta(days=1)

    raise RuntimeError("Impossible de calculer la période active")
