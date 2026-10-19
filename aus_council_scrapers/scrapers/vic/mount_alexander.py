"""Mount Alexander Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Mount Alexander splits its meetings across two OpenCities lists, like
Kingston:

* **Past**—``OC CL Public Past Meetings`` at ``/Past-Council-Meetings``,
  from 2018.
* **Upcoming**—``OC CL Public Upcoming Meetings`` at
  ``/Upcoming-Council-meetings``.

**Agendas exist only on the upcoming list.** Once a meeting is held its
agenda is taken down, and the past list keeps the minutes and the
"Supporting Information" attachment books (checked across every past
meeting, October 2026). So the history here is minutes-only, and an agenda is
caught only while its meeting is upcoming: 20 October 2026's was there on 20
October. A nightly run picks each one up in the week or so it is online,
and once the meeting moves to the past list its record keeps the minutes
alone.

Papers are one flat list labelled by filename-like text—"Meeting of Council
19 May 2026 - Minutes.pdf", "Meeting of Council Agenda 20 October 2026"—so
``papers_by = "link_text"``. Attachment books ("Supporting Information",
"Supporting Documents 1") are passed over. One label names neither paper
("Council Meetings - 18 April 2023 -"), so `papers` adds the filename to a
label that says neither ("meeting_of_council_minutes_18_april_2023.pdf").

The Council Meeting rows of 18 November 2025 and 26 November 2024 also hold
an Unscheduled Meeting of Council's minutes, and that meeting has no row of
its own. `split_off` reports it as a meeting of its own, so 18 November 2025
is two records and 26 November 2024—whose only paper is the unscheduled
meeting's minutes—is one, named for that meeting.

The listing dates the 17 March 2020 Council Meeting as 16 March; its page and
minutes say 17 March, and `meeting_date` uses that.

Meeting types are only Council and Unscheduled Meetings of Council, so
nothing is filtered out. One production year is the two list pages and a
payload per meeting: 14 requests for 2026.
"""

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    _AGENDA,
    _MINUTES,
    Listing,
    ListingRow,
    _is_pdf,
    _label,
)
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

_BASE_URL = "https://www.mountalexander.vic.gov.au/Council/Council-meetings"

_UNSCHEDULED = re.compile(r"^Unscheduled Meeting of Council\b", re.IGNORECASE)


def _unscheduled_links(soup: BeautifulSoup) -> list:
    return [
        anchor
        for anchor in soup.find_all("a", href=True)
        if _is_pdf(anchor["href"].strip())
        and _UNSCHEDULED.match(_label(anchor.get_text(" ", strip=True)))
    ]


@register_scraper
class MountAlexanderScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 28 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    list_name = "OC CL Public Past Meetings"
    papers_by = "link_text"

    def __init__(self):
        super().__init__("mount_alexander", "VIC", f"{_BASE_URL}/Past-Council-Meetings")

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            Listing(
                f"{_BASE_URL}/Upcoming-Council-meetings",
                "OC CL Public Upcoming Meetings",
            )
        ]

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            label = _label(anchor.get_text(" ", strip=True))
            if _is_pdf(href) and not (_AGENDA.search(label) or _MINUTES.search(label)):
                filename = urlparse(href).path.rsplit("/", 1)[-1]
                anchor.string = f"{label} {filename}"
        return super().papers(content)

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        if row.meeting_type.lower().startswith("unscheduled"):
            return super().build_returns(content, row)
        return self.split_off(
            content, row, _unscheduled_links, "Unscheduled Meeting of Council"
        )
