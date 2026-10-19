"""District Council of Lower Eyre Peninsula.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The site now
titles the council "Lower Eyre Council".

Titles name only the month ("Agenda - October 2026"), so the day comes from
the date each document is filed under. That is usually the meeting's, but
not always, and the uploaded file's name then has it right:

- "Agenda - February 2023" of the Cummins Homes Committee is filed under
  3 February, its file is CHC_20230209_AGN_29_AT.PDF, and the agenda's own
  front page calls the meeting for 9 February, where its minutes are filed.
- "Agenda - January 2022" of the Eyre Peninsula Regional Assessment Panel is
  filed under 18 January 2021, a year early; its file is
  Agenda-Eyre-Regional-Assessment-Panel-18-January-2022.PDF, and its front
  page says Tuesday 18 January 2022.
- Two of the panel's papers are filed under 1 January, Matrix's placeholder,
  with the meeting date only in the file name (...-20260914-Final.pdf).

So a file name stating a full date in the month the title names replaces
the filed date. Those four documents are the only ones on the listing whose
file name and filed date disagree.

A document whose title names another month than the one it ends up in has no
day of its own. The Cummins Homes Committee's "Minutes - May 2025" is filed
under 1 March 2025 as Minutes-May-2025.pdf, and its front page says Thursday
1 May 2025: the committee's only meeting that May, whose agenda is filed on
the 1st. So such a document joins the one meeting of its body in the month
its title names, when there is exactly one and it lacks that kind of paper.
Otherwise it is left out rather than put on a meeting that did not happen.

Both corrections are made to the listing as read, before the base class
sorts documents into years. The January 2022 panel agenda is filed in 2021,
so redating it inside a year's group would leave it out of a run that asks
for 2022 alone, which is what production does.
"""

import dataclasses
import datetime
import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import (
    LGASAFunnelbackScraper,
    _classify,
    _Listed,
    _title_date,
    _words,
)

_TITLE_MONTH = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "CHC_20230209_AGN_29_AT.PDF", "141350-AGENDA-EPRAP-MEETING-20260914-Final.pdf".
_FILE_YMD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def _title_month(title: str) -> Optional[tuple[int, int]]:
    match = _TITLE_MONTH.search(title)
    if not match:
        return None
    month = datetime.datetime.strptime(match.group(1)[:3], "%b").month
    return int(match.group(2)), month


def _file_date(filename: str) -> Optional[datetime.date]:
    stated = _title_date(_words(filename))
    if stated is not None:
        return stated
    match = _FILE_YMD.search(filename)
    if not match:
        return None
    try:
        return datetime.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _month_of(iso_date: str) -> tuple[int, int]:
    return int(iso_date[:4]), int(iso_date[5:7])


def _kind(listed: _Listed) -> Optional[str]:
    classified = _classify(listed.title, listed.filename)
    return classified[0] if classified else None


@register_scraper
class LowerEyrePeninsulaScraper(LGASAFunnelbackScraper):
    # The whole collection: Council, the Council Assessment Panel (to 2021),
    # the Eyre Peninsula Regional Assessment Panel that replaced it, the
    # audit committee and the section 41 committees.
    listing_urls = (
        "https://www.lowereyrepeninsula.sa.gov.au/council/agenda-and-minutes",
    )

    # One committee filed under two spellings since 2022.
    committee_names = {"Audit & Risk Committee": "Audit and Risk Committee"}

    def __init__(self):
        super().__init__(
            "lower_eyre_peninsula", "SA", "https://www.lowereyrepeninsula.sa.gov.au"
        )

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        return self._redated(super()._listing_documents(listing_url, earliest_year))

    def _redated(self, documents: list[_Listed]) -> list[_Listed]:
        """The listing with each document moved to its meeting's day.

        See the module docstring for the two rules and the cases behind them.
        """
        by_file = [self._dated_by_file(listed) for listed in documents]
        settled = [
            listed
            for listed in by_file
            if listed.date is not None
            and _title_month(listed.title) in (None, _month_of(listed.date))
        ]
        redated = []
        for listed in by_file:
            month = _title_month(listed.title)
            if listed.date is None or month in (None, _month_of(listed.date)):
                redated.append(listed)
                continue
            date = self._only_meeting_in(month, listed, settled)
            if date is None:
                self.logger.info(
                    f"{self.council_name}: left out ?a={listed.asset_id} "
                    f"{listed.title!r}, filed {listed.date}: no single "
                    f"{listed.committee!r} meeting in the month its title names"
                )
                continue
            redated.append(dataclasses.replace(listed, date=date))
        return redated

    @staticmethod
    def _dated_by_file(listed: _Listed) -> _Listed:
        month = _title_month(listed.title)
        if listed.date is None or month is None:
            return listed
        stated = _file_date(listed.filename)
        if (
            stated is not None
            and stated.isoformat() != listed.date
            and (stated.year, stated.month) == month
        ):
            return dataclasses.replace(listed, date=stated.isoformat())
        return listed

    def _only_meeting_in(
        self, month: tuple[int, int], listed: _Listed, settled: list[_Listed]
    ) -> Optional[str]:
        """The day of the one meeting of `listed`'s body in `month`, when
        there is exactly one and it has no paper of `listed`'s kind yet."""
        body = self._body_name(listed.committee)
        same_body = [
            other
            for other in settled
            if _month_of(other.date) == month
            and self._body_name(other.committee) == body
        ]
        days = {other.date for other in same_body}
        if len(days) != 1:
            return None
        (day,) = days
        kind = _kind(listed)
        if kind is None or any(_kind(other) == kind for other in same_body):
            return None
        return day
