"""Campaspe Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Council Meetings,
Unscheduled Meetings and Special Meetings, all of the council, so nothing is
filtered out. The listing includes the next meeting as soon as its agenda is
up (20 October 2026, checked on 19 October), and has nothing before 2019.

Papers are filed under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>``, every
link labelled "Download PDF", so ``papers_by = "heading"``. Attachment books
sit in nested sections under the same headings and are passed over. Since
2023 the agenda is one file with its attachments bound in
("…-agenda-and-attachments.pdf", up to 99 MB).

Three meetings need more than the base class does:

* **A second copy of the minutes under the Agenda heading.** 14 November
  2023's "agenda" is "…-unscheduled-council-meeting-minutes2.pdf", a copy of
  that meeting's minutes (both scans open "Date: 14 November 2023 / Time:
  5:36 pm"). The base class already refuses a file named as minutes there,
  but "minutes2" is one word to it, so `papers` drops any agenda whose
  filename says minutes and not agenda. The 26 October and 4 November 2022
  rows file signed minutes the same way, and the base class catches those.
* **Two meetings on one row.** 17 November 2021 holds an Unscheduled Council
  Meeting and the Council Meeting, each with an agenda and minutes, under
  "Agenda - Unscheduled Council Meeting" and "Minutes - Unscheduled" beside
  "Agenda - Open Council Meeting" and "Minutes". Read as one record, the
  unscheduled meeting's agenda would sit with the other meeting's minutes, so
  it becomes two records (`split_off`).

One production year is the listing page and a payload per meeting: 13
requests for 2026. The site is behind Cloudflare as well as Akamai
(``server: cloudflare``, ``cf-ray``), with no challenge seen from a home
connection in October 2026; a GitHub runner has not been tried.
"""

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

_UNSCHEDULED = re.compile(r"\bunscheduled\b", re.IGNORECASE)


def _named_minutes(url: str) -> bool:
    # No word boundary after "minutes": the 14 November 2023 copy is
    # "minutes2".
    name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    return "minutes" in name and "agenda" not in name


def _unscheduled_sections(soup: BeautifulSoup) -> list:
    sections = []
    for section in soup.find_all("div", class_="meeting-document"):
        heading = section.find("h3")
        if heading and _UNSCHEDULED.search(heading.get_text(" ", strip=True)):
            sections.append(section)
    return sections


@register_scraper
class CampaspeScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 24 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    papers_by = "heading"

    def __init__(self):
        super().__init__(
            "campaspe",
            "VIC",
            "https://www.campaspe.vic.gov.au/Our-council/Council-meetings/Agendas-minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers = super().papers(content)
        if papers.get("agenda") and _named_minutes(papers["agenda"]):
            del papers["agenda"]
        return papers

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        if _UNSCHEDULED.search(row.meeting_type):
            return super().build_returns(content, row)
        return self.split_off(
            content, row, _unscheduled_sections, "Unscheduled Meeting"
        )
