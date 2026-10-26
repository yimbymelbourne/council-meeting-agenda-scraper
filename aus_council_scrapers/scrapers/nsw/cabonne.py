"""Cabonne Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds the Council's meetings and its
committees'. The committees are named after the Council's own meeting
type—"Infrastructure (Transport) Ordinary Meeting", "Community, Economy &
Culture Ordinary Meeting", "Environment, Innovation & Energy Committee
Ordinary Meeting"—so ``meeting_types`` is anchored at both ends: only
"Ordinary Meeting" and "Extraordinary Meeting" are the Council. The
committees are about 15 of the 26 rows a year, and each listed meeting costs
a payload request.

The ``dlv_`` year filter offers 2013–2026, but in October 2026 the years
before 2023 held one row between them (25 February 2020); 2021 and 2022 are
empty. The council's documents online effectively start in 2023.

Papers are filed under headings—"Agenda", "Supplementary Reports",
"Minutes"—each paper a "Download PDF" link, so ``papers_by = "heading"``.
The Minutes section also links an HTML copy on ``cabonne.infocouncil.biz``;
heading mode takes the section's PDF and passes the HTML link by. That
InfoCouncil site holds only minutes, from April 2026, and is not read.

Two Minutes headings are misspelt, "Minuites" (22 October 2024) and
"Miinutes" (27 June 2023); `papers` corrects them, or those meetings would
lose their minutes. Two Council meetings have an agenda and no minutes file
(28 March 2023, 22 April 2025), and the 8 October 2024 Extraordinary
Meeting has minutes and no agenda (checked October 2026).

The agenda PDFs carry their attachments: 22 September 2026's is 133 MB.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=50)`` page held all 26 of 2026's rows to date, and the
filtered page carries the full year dropdown. So a production year is one
listing request plus one payload per Council meeting, where the default ten
rows a page would be three listing requests.

robots.txt disallows about 1,400 per-meeting pages under this listing
(``.../Agendas-and-Minutes/20230228-Council-Meeting/20230228-Agenda`` and the
like). The scraper requests none of them: it reads the listing and the
``OCServiceHandler.axd`` payloads only.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# The misspelt Minutes headings, matched whole so nothing else is renamed.
_MINUTES_TYPO = re.compile(r"^(?:minuites|miinutes)$", re.IGNORECASE)


@register_scraper
class CabonneScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 9
    # requests (one listing page and 8 payloads), 15 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 15

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = re.compile(r"^(?:ordinary|extraordinary) meeting$", re.IGNORECASE)

    def __init__(self):
        super().__init__(
            "cabonne",
            "NSW",
            "https://www.cabonne.nsw.gov.au/Council/About-Council/"
            "Council-and-Committee-Meetings/Agendas-and-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            if _MINUTES_TYPO.match(heading.get_text(" ", strip=True)):
                heading.string = "Minutes"
        return super().papers(content)
