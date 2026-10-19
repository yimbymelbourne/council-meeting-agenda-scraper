"""Murrindindi Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Agendas and Minutes" (``OC CL Public Meetings``). The year
filter offers 2012–2026; 2020 onwards is fetched.

Papers sit under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>`` with every link
"Download PDF", so `papers_by = "heading"`. The Agenda section also nests a
Related Information list of item attachments, some of them other bodies'
minutes (the Audit and Risk Committee's, filed as an attachment to the
Council report that notes them). Heading mode takes the section's own PDF
and never those nested lists.

Types are Scheduled, Unscheduled, Ordinary and Special Meeting, all of
Council, so nothing is filtered by type. One row is left out: 17 April 2020,
typed Special Meeting, whose payload is "Minutes and Attachments for the
Chief Executive Officer Exercise of Delegation". That is the record of a
decision the CEO made under delegation during the COVID-19 restrictions, not
a meeting, and its only paper is that record filed under "Minutes".

One production year is one listing page (pagesize=100; 2020, the busiest
year, has 19 rows) plus one payload per meeting: 13 requests for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

_DELEGATION = re.compile(r"\bexercise\s+of\s+delegation\b", re.IGNORECASE)


@register_scraper
class MurrindindiScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 25 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "murrindindi",
            "VIC",
            "https://www.murrindindi.vic.gov.au/Council/Council-Meetings/Agendas-and-Minutes",
        )
        self.default_name = "Council Meeting"

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        opening = content.find("p")
        if opening and _DELEGATION.search(opening.get_text(" ", strip=True)):
            self.logger.info(
                f"{row.date}: a record of CEO delegation, not a meeting; skipped"
            )
            return None
        return super().build_return(content, row)
