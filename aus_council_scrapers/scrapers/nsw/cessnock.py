"""Cessnock City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every Ordinary and Extraordinary
Council meeting back to 2016, upcoming meetings included once their agenda is
up. Those are the only two meeting types the filter offers, so nothing is
allowlisted.

Papers are filed under headings—``<h3>Agenda</h3>``, ``Minutes``,
``Enclosures``, ``Supplementary Agenda``, ``Enclosure Under Separate Cover -
…``—with every link labelled "Download PDF", so ``papers_by = "heading"``.
Since late 2025 the agenda heading is "Agenda and Enclosures": one PDF with
the enclosures bound in, which is still the agenda. The 16 February 2022
meeting files its PDF agenda under the plural "Agendas and enclosures",
which the base class's ``agenda\b`` rule passes over (the "s" breaks the
word boundary), so `papers` rewrites a leading "Agendas" to "Agenda" first.

**Most agendas before October 2022 are ZIP files**, not PDFs ("Download ZIP
(125MB)" under "Agenda" or "Agenda and enclosures"), so those meetings carry
minutes only. That is deliberate: a ZIP is not a document anyone can open
from a link, and the minutes are the PDF of record. 16 February 2022 is the
exception, with a PDF. 1 April 2020 has a row and no papers at all, and is
skipped.

The 2020 year filter also returns 17 February 2021—the council filed that
meeting under 2020. The base class logs it as a stray; with ``page_size`` the
2020 listing is one page anyway, so nothing is lost from the recorded
history. A one-year 2021 run would miss that meeting, which production (the
current year only) never asks for.

``page_size`` makes each year one listing request, and the filtered page
carries the full year dropdown, so ``year_filtered_first_page`` skips the
bare page. One production year is then one listing request plus a payload
per meeting: 14 for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# "Agendas and enclosures" (16 February 2022): the plural is still the agenda.
_PLURAL_AGENDA = re.compile(r"^agendas\b", re.IGNORECASE)


@register_scraper
class CessnockScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 14 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # Measured October 2026: the year filter with (pagesize=50) returns the
    # whole year on one page, and that page offers every year in its
    # dropdown, so the bare first page is not needed.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "cessnock",
            "NSW",
            "https://www.cessnock.nsw.gov.au/Council/Council-meetings/Minutes-and-agendas",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            if not h3:
                continue
            heading = re.sub(r"\s+", " ", h3.get_text(" ", strip=True))
            tidied = _PLURAL_AGENDA.sub("Agenda", heading, count=1)
            if tidied != heading:
                h3.string = tidied
        return super().papers(content)
