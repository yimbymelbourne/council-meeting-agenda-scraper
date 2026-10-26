"""Mildura Rural City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Ordinary Meetings,
Special Meetings (the annual mayoral meeting among them) and the Planning
Delegated Committee. All three are council or planning bodies, so nothing is
filtered out.

Papers are one flat "Related Information" list labelled by link text—
"Agenda - Ordinary Meeting of Council - 22 October 2026", "DRAFT Minutes -
…", "CONFIRMED Minutes - …"—so ``papers_by = "link_text"``. Confirmed or
plain minutes win over draft ones when a meeting lists both (26 March 2026).
Labels from early 2020 are bare filenames ("Download-Agenda.pdf"). Every
meeting also lists a "Public Notice" of the meeting, which mentions neither
word and is passed over. Supplementary agendas are left out by the base
class, and so are "Urgent Agenda" papers (22 May 2025, 24 July 2025, 24 April
2024): an urgent-business paper beside the meeting's real agenda.

The listing dates 25 August 2022's Ordinary Meeting as 24 August; its page
and papers say 25 August, and `meeting_date` uses that. The 15 July 2021
Special Meeting keeps its listed date: its agenda was issued for 14 July,
but its minutes record the meeting held at 2 pm on Thursday 15 July.

The year filter offers 2013 onwards; 2020 onwards is fetched. One production
year is the listing page and a payload per meeting: 15 requests for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import _label
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

_URGENT = re.compile(r"^urgent\b", re.IGNORECASE)


@register_scraper
class MilduraScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 28 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    papers_by = "link_text"

    def __init__(self):
        super().__init__(
            "mildura",
            "VIC",
            "https://www.mildura.vic.gov.au/Council/Council-meetings/Agendas-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for anchor in content.find_all("a", href=True):
            if _URGENT.match(_label(anchor.get_text(" ", strip=True))):
                anchor.decompose()
        return super().papers(content)
