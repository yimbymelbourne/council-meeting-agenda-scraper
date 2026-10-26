"""Meeting dates for regional assessment panels on LGA SA listing pages.

Wakefield and Yankalilla each publish a regional assessment panel on a page of
its own, and both panels file their papers under dates that are often not the
meeting's, while every title or file name states the meeting date:

- Matrix's 1 January placeholder. Mid North's "24 July 2025 - Mid North
  Regional Assesment Panel Minutes" is filed under 1 January 2025, and its
  15 December 2022 agenda and minutes under 1 January 2023.
- The upload day. Mid North's "24 February 2026 ... Minutes" is filed under
  27 February.
- A month out. Fleurieu's FRAP-Minutes-26-August-2025.pdf is filed under
  26 July 2025, where it made a minutes-only meeting of its own beside the
  22 July meeting.

So on a panel page the stated date replaces the filed date. The file name wins
when it and the title disagree: Mid North's "12 March 2025 - ... Minutes",
filed under 1 January 2026, is Mid-North-Regional-Assessment-Panel-Minutes-
12-March-2026.pdf, and its front page says Thursday 12 March 2026. A stated
date more than `_WINDOW_DAYS` from a real filed date is left alone, so a title
naming some other meeting cannot move a paper across the year.

The listing is corrected as it is read, before the base class sorts documents
into years, so the December 2022 papers filed in 2023 reach a run that asks
for 2022 alone.
"""

import dataclasses
import datetime
from typing import Optional

from aus_council_scrapers.lgasa import _Listed, _title_date, _words

# Covers the month-out filing above (31 days) with room to spare, and is well
# short of a year, which no filing error here comes near except the
# placeholder.
_WINDOW_DAYS = 45


def _stated_date(listed: _Listed) -> Optional[datetime.date]:
    return _title_date(_words(listed.filename)) or _title_date(listed.title)


def dated_as_stated(listed: _Listed) -> _Listed:
    """`listed`, moved to the meeting date its file name or title states."""
    stated = _stated_date(listed)
    if stated is None or listed.date is None:
        return listed
    filed = datetime.date.fromisoformat(listed.date)
    if stated == filed:
        return listed
    placeholder = (filed.month, filed.day) == (1, 1) and stated.year in (
        filed.year,
        filed.year - 1,
    )
    if placeholder or abs((stated - filed).days) <= _WINDOW_DAYS:
        return dataclasses.replace(listed, date=stated.isoformat())
    return listed
