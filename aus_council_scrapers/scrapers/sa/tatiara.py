"""Tatiara District Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. There is no
page over the whole collection: each committee page under
/your-council/committees-of-council lists that committee only, and the
council's own page lists its meetings under "Council Agenda & Minutes", which
the base class reads as the council itself. That page and the regional
assessment panel's are read.

Three things on the council page need handling beyond the base class, all filed
under the council's own label:

- Briefing sessions and informal gatherings, often on the evening of a
  council meeting ("2026 April 14 Council Briefing Session Notes"). They are
  informal gatherings, which cannot make decisions, and their "Notes" would
  otherwise be read as the minutes of a council meeting that never sat
  (5 May 2026, and about a dozen dates in 2020-21).
- Confidential items released one at a time ("2025 July 8 Confidential
  Council Minutes - RFQ 39-24/25 Rubble Raising and Crushing"). Each is one
  item's extract, never the meeting's minutes, and filed a day off the
  meeting it stood in for it: 22 January 2025 and 26 June 2024 came out as
  meetings of their own.
- Titles lead with the date in year-month-day order ("2024 September 10
  Council Agenda"), which the base class does not read, so a meeting filed
  under the wrong day kept it: 10 September 2024 was dated the 6th.
"""

import datetime
import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper

_NOT_A_MEETING = re.compile(
    r"\bbriefing\s+sessions?\b|\binformal\s+gathering", re.IGNORECASE
)
_CONFIDENTIAL = re.compile(r"\bconfidential\b", re.IGNORECASE)

# "2024 September 10 Council Agenda".
_LEADING_DATE = re.compile(r"^(\d{4})\s+([A-Za-z]+)\s+(\d{1,2})\b")

# How far a title's day may be from the filed day and still replace it. The
# title's *year* is wrong often enough to never be trusted ("2024 April 14
# Council Briefing Session Notice" filed 14 April 2026, "2022 April 22
# Special Council Minutes" filed 22 April 2025), so a title in another year
# leaves the filed date alone.
_TITLE_DAY_WINDOW = 7


def _leading_date(title: str) -> Optional[datetime.date]:
    match = _LEADING_DATE.match(title)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime.datetime.strptime(
            f"{day} {month[:3]} {year}", "%d %b %Y"
        ).date()
    except ValueError:
        return None


@register_scraper
class TatiaraScraper(LGASAFunnelbackScraper):
    # Council and the Northern Limestone Coast Regional Assessment Panel,
    # which decides development applications for Tatiara and its neighbours.
    # No other scraper reads the panel. Its titles lead with the date in the
    # same year-month-day order as the council's, so the same date rule
    # serves both pages. The audit committee's page
    # (/your-council/committees-of-council/audit-committee) is not read: it
    # would cost one more Selenium page and a 20 s crawl delay a night.
    listing_urls = (
        "https://www.tatiara.sa.gov.au/your-council/council-agenda-and-minutes",
        "https://www.tatiara.sa.gov.au/your-council/committees-of-council/"
        "northern-limestone-coast-regional-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 23 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 23

    def __init__(self):
        super().__init__("tatiara", "SA", "https://www.tatiara.sa.gov.au")

    def _assemble(self, documents, year):
        return super()._assemble(
            [
                d
                for d in documents
                if not _NOT_A_MEETING.search(d.title)
                and not _CONFIDENTIAL.search(d.title)
            ],
            year,
        )

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        stated = _leading_date(title)
        if stated is not None:
            filed_day = datetime.date.fromisoformat(filed)
            if (
                stated.year == filed_day.year
                and 0 < abs((stated - filed_day).days) <= _TITLE_DAY_WINDOW
            ):
                return stated.isoformat()
        return super()._meeting_date(filed, title, year)
