"""Regional Council of Goyder.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The site titles
the council "Goyder Regional Council". /council/meetings carries no listing;
the ordinary-meetings page under it lists the council's own meetings, filed
under "Meetings of Council". Late reports are filed as documents of their own
("11.1 Late Report ..."), which the base class never takes for the agenda.

Titles give the meeting date as day.month.year, often with a two-digit year
("Confirmed Minutes 18.08.26"), which the base class does not read. The
confirmed minutes of 18 April 2023 ("Minutes 18.04.23") were filed under 18
May, a month later, so read by the filed date that meeting had an agenda and
no minutes and a minutes-only meeting appeared on 18 May. Read by the title,
they rejoin their agenda.
"""

import datetime
import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper

_DOTTED_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?![\d.])")

# How far a title's date may be from the filed date and still replace it: the
# month-late filing above, but not "04.05.2025 Special Meeting Council
# Agenda", filed 4 March 2025 beside "Confirmed Minutes Special 04.03.2025",
# whose title is two months out and wrong.
_TITLE_DAY_WINDOW = 31


def _dotted_date(title: str) -> Optional[datetime.date]:
    match = _DOTTED_DATE.search(title)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(
            int(year) + (2000 if len(year) == 2 else 0), int(month), int(day)
        )
    except ValueError:
        return None


@register_scraper
class GoyderScraper(LGASAFunnelbackScraper):
    # Council only. The committee pages under /council/committees-sa (audit,
    # CEO performance, Burra and Goyder advisory committees) would each cost
    # one more Selenium page and a 20 s crawl delay a night. Goyder's
    # planning body, the Mid North Regional Assessment Panel, has no page on
    # Goyder's site; `WakefieldScraper` reads it from Wakefield's.
    listing_urls = ("https://www.goyder.sa.gov.au/council/meetings/ordinary",)

    committee_names = {
        "Meetings of Council": "Council Meeting",
        "Ordinary Meetings of Council": "Council Meeting",
    }

    def __init__(self):
        super().__init__("goyder", "SA", "https://www.goyder.sa.gov.au")

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        stated = _dotted_date(title)
        if stated is not None:
            filed_day = datetime.date.fromisoformat(filed)
            if (
                stated.year == filed_day.year
                and 0 < abs((stated - filed_day).days) <= _TITLE_DAY_WINDOW
            ):
                return stated.isoformat()
        return super()._meeting_date(filed, title, year)
