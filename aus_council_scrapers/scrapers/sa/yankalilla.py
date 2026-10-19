"""District Council of Yankalilla.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The
/council/agenda-and-minutes index carries no listing; each page under it
lists one committee, so the council-meetings page and the Fleurieu Regional
Assessment Panel's page are read. The council page's five scans of 1940s and
1950s minutes are older than `EARLIEST_YEAR` and never requested as
meetings.

The panel's papers are titled with their file names, which state the meeting
date, while the date they are filed under is sometimes a month out; they are
dated as stated, see `lgasa_panel_dates`.
"""

import datetime
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper, _Listed, _title_date
from aus_council_scrapers.scrapers.sa.lgasa_panel_dates import dated_as_stated

_PANEL_PAGE = (
    "https://www.yankalilla.sa.gov.au/council/agenda-and-minutes/"
    "fleurieu-regional-assessment-panel"
)

# How far a title's date may be from the filed date and still replace it.
# Titles here always state the meeting date ("Special Council Minutes - 10
# June 2022"), and the filed date is sometimes the upload day instead: those
# minutes were filed 17 June, while a single released item ("Special Council
# Meeting - 10 June 2022 - 5.1 Chief Executive Officer Recruitment Minutes")
# was filed on the 10th and stood in for them. Read by the title, both sit on
# the 10th and the full minutes win. A week covers every mismatch on the
# listing (2 and 7 days) without reaching the next meeting.
_TITLE_DAY_WINDOW = 7


@register_scraper
class YankalillaScraper(LGASAFunnelbackScraper):
    # Council and the Fleurieu Regional Assessment Panel, which decides
    # development applications for Yankalilla and Victor Harbor. No Victor
    # Harbor scraper exists yet, so this is the only scraper that reads it.
    # The Audit and Risk Committee page is not read: it would cost one more
    # Selenium page and a 20 s crawl delay a night. The Strategic Planning
    # and Development Policy Committee page stops in April 2016.
    listing_urls = (
        "https://www.yankalilla.sa.gov.au/council/agenda-and-minutes/council-meetings",
        _PANEL_PAGE,
    )

    # One production year, measured 20 Oct 2026 from a home IP: 27 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 27

    def __init__(self):
        super().__init__("yankalilla", "SA", "https://www.yankalilla.sa.gov.au")

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        documents = super()._listing_documents(listing_url, earliest_year)
        if listing_url != _PANEL_PAGE:
            return documents
        return [dated_as_stated(listed) for listed in documents]

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        stated = _title_date(title)
        if stated is not None:
            filed_day = datetime.date.fromisoformat(filed)
            if (
                stated.year == filed_day.year
                and 0 < abs((stated - filed_day).days) <= _TITLE_DAY_WINDOW
            ):
                return stated.isoformat()
        return super()._meeting_date(filed, title, year)
