"""Indigo Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Agendas and minutes" (``OC CL Public Meetings``). The council
removes papers older than 12 months (the page says they are available by
email), so only 2025 and 2026 have rows, although the year filter offers
2013 onwards.

Papers sit under headings—"Agenda - 25 August 2026", "Minutes - 25 August
2026"—with every link "Download PDF", so `papers_by = "heading"`. Two quirks:

* The Agenda section also carries the Capital Works Monitor, an item
  attachment, as a second link and again in an untitled section of its own.
  Heading mode takes the section's first PDF, which is the agenda, and skips
  sections with no heading.
* The 29 September 2026 heading says "Agenda - 29 September 2029". The date
  comes from the listing row, never the heading, so the typo is harmless.

On 25 November 2025 one listing row holds two meetings: the Statutory
Council Meeting (to elect the Mayor) and the Scheduled Council Meeting held
straight after it, each with its own agenda and minutes, headed "Agenda -
Statutory Council Meeting - 25 November 2025" and so on. Read as one meeting,
the statutory papers win and the scheduled meeting's agenda and minutes are
lost, so `build_returns` splits such a row into one record per body.

Meeting types are Scheduled and Additional Meetings, all of Council. One
production year is one listing page (pagesize=100) plus one payload per
meeting: 9 requests for 2026.
"""

import copy
import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _label,
)

# "Agenda - Statutory Council Meeting - 25 November 2025": a paper heading that
# names its body between the paper and the date. A plain "Agenda - 25 August
# 2026" has no body and does not match.
_BODY_HEADING = re.compile(
    r"^(?:agenda|minutes)\s*-\s*(?P<body>[a-z]+)\b.*?\s-\s*\d{1,2}\s+[a-z]+\s+\d{4}$",
    re.IGNORECASE,
)


def _body(section) -> str | None:
    h3 = section.find("h3")
    match = _BODY_HEADING.match(_label(h3.get_text(" ", strip=True))) if h3 else None
    return match.group("body").title() if match else None


@register_scraper
class IndigoScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 18 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 18

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "indigo",
            "VIC",
            "https://www.indigoshire.vic.gov.au/About-Council/Council-Meetings/Agendas-and-minutes",
        )
        self.default_name = "Council Meeting"

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        bodies = []
        for section in content.find_all("div", class_="meeting-document"):
            body = _body(section)
            if body and body not in bodies:
                bodies.append(body)
        if len(bodies) < 2:
            return super().build_returns(content, row)

        # One record per body, each read from a copy of the payload holding
        # only that body's paper sections. Untitled and plainly titled
        # sections stay in every copy; the base rules skip them as before.
        records = []
        for body in bodies:
            part = copy.copy(content)
            for section in part.find_all("div", class_="meeting-document"):
                other = _body(section)
                if other and other != body:
                    section.decompose()
            record = self.build_return(part, row)
            if record is not None:
                record.name = f"{body} Meeting"
                records.append(record)
        return records
