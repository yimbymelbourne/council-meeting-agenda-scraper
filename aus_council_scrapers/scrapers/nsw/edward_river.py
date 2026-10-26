"""Edward River Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2016, and its
year filter is exact: the per-year counts add up to the unfiltered listing's
153 results (checked 20 October 2026).

Each row links a page of its own, but it also carries a ``data-cvid`` and the
renderer answers for it (checked 20 October 2026), so the cheaper renderer
payload is read rather than the meeting's page (``detail_pages`` stays off).

The payload is one flat "Related Information" list labelled by filename, so
``papers_by = "link_text"``. The agenda's name has changed over the years:
"Council-Business-Paper-17-December-2020.pdf" and
"Business-Papers-15-July-2021.pdf" until 2021, then
"Agenda-for-Ordinary-Council-Meeting-…" or "Public-Agenda-for-…". "Business
paper" is the NSW name for the agenda, so it counts as one (`papers`). So
does a file named only for the meeting and its date: the 2 December 2021
extraordinary meeting's 15 MB agenda is
"Extra-Ordinary-Council-Meeting-2nd-December-2021.pdf", beside
"Draft-Minutes-Extraordinary-Council-Meeting-2-December-2021.pdf". Beside
them are supplementary agendas and reports, passed over, and the minutes,
which are "Draft Minutes" until confirmed; the base class prefers confirmed
minutes where a meeting has both, and otherwise reports the draft. Two
meetings have only one paper online: 1 July 2026 (minutes only) and 15
November 2022 (agenda only).

Meeting types are Ordinary and Special Meetings only (the special ones are
the council's extraordinary meetings), so nothing is filtered: one
production year is about 11 requests. The site is behind Akamai
(``Server-Timing: ak_p``), which served the identifying User-Agent without a
challenge from a home IP; it has not been measured from a GitHub runner.
robots.txt disallows nothing on the meetings pages.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import _MINUTES, OpenCitiesMeetingsScraper

_BUSINESS_PAPER = re.compile(r"\bbusiness[\s-]+papers?\b", re.IGNORECASE)

# A file named for the meeting and its date and nothing else:
# "Extra-Ordinary-Council-Meeting-2nd-December-2021.pdf".
_MEETING_ONLY = re.compile(
    r"^(?:extra[\s-]*)?ordinary[\s-]+council[\s-]+meeting[\s-]+\d", re.IGNORECASE
)


@register_scraper
class EdwardRiverScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 19 s
    # (11 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "edward_river",
            "NSW",
            "https://www.edwardriver.nsw.gov.au/Council/Council-Meetings/Minutes-and-Agendas",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for anchor in content.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            renamed = _BUSINESS_PAPER.sub("Agenda", text)
            if _MEETING_ONLY.match(renamed) and not _MINUTES.search(renamed):
                renamed = f"Agenda {renamed}"
            if renamed != text:
                anchor.string = renamed
        return super().papers(content)
