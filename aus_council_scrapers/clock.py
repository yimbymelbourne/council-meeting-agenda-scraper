"""The project's notion of "now".

Scrapers build URLs and year ranges from the current year — an InfoCouncil
scraper asks for every year from `EARLIEST_YEAR` to two years out. That makes
their recorded cassettes expire on a calendar boundary rather than on a code
change: come January the range grows by one, the scraper requests a year the
cassette has never seen, and the test fails for no reason anyone caused.

Routing those reads through here lets replay pin the clock to the date the
cassette was recorded, so a fixture stays valid until the scraper or the
council's website actually changes.

Scrapers should use `clock.today()` / `clock.current_year()` rather than
`datetime.date.today()`.
"""

from __future__ import annotations

import datetime
from contextlib import contextmanager

_frozen_date: datetime.date | None = None


def today() -> datetime.date:
    """The current date, or the pinned date during replay."""
    return _frozen_date if _frozen_date is not None else datetime.date.today()


def current_year() -> int:
    return today().year


def freeze(date: datetime.date | str) -> None:
    """Pin `today()` to a fixed date."""
    global _frozen_date
    if isinstance(date, str):
        date = datetime.date.fromisoformat(date)
    _frozen_date = date


def unfreeze() -> None:
    global _frozen_date
    _frozen_date = None


@contextmanager
def frozen(date: datetime.date | str):
    previous = _frozen_date
    try:
        freeze(date)
        yield
    finally:
        globals()["_frozen_date"] = previous
