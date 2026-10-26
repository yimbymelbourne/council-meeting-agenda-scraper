"""City of Unley—OpenCities, on `OpenCitiesMeetingsScraper`.

Unley gives each meeting body its own listing page under
``/Council/About-the-Council/Meetings-minutes``. Two are read:

* **Full Council Meetings**—ordinary and special Council meetings, from
  April 2019, with upcoming meetings listed ahead of their agendas.
* **Council Assessment Panel**—the planning body, listed through December of
  the current year from the start of it, so most of its upcoming rows have no
  papers yet and are skipped.

Both pages carry the same widget under the same internal name (``Full
Council Meetings``), so the ``dlv_`` year filter works on each. The other
bodies—Audit & Risk, Strategic Property, Elected Member briefings, the
Business Economic Development Advisory Committee and the City Strategy and
Development Policy Committee (three meetings in all, none since 2024)—are
neither Council nor planning bodies, and each listed meeting costs a payload
request, so they are left out.

Papers are filed under headings (``<h3>Agenda</h3>``, ``<h3>Minutes</h3>``),
so ``papers_by = "heading"``.

The listing calls every Council meeting "Full Council". Special meetings are
told apart only by their papers' filenames ("special-council-agenda-15-
september-2025"), so those are named "Special Council Meeting" and the rest
"Council Meeting".

One production year is two filtered listing pages per body (the first of
them also gives the year dropdown, so no unfiltered page is fetched) and one
payload per meeting: 29 requests and 55 s for 2026, measured in October
2026, 25 of them payloads. Every one of those is a Council or CAP meeting,
so there is nothing left to cut but the CAP's November and December rows,
which have no papers until a week before each sits.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    Listing,
    ListingRow,
    OpenCitiesMeetingsScraper,
)

_BASE = "https://www.unley.sa.gov.au/Council/About-the-Council/Meetings-minutes"
_LIST_NAME = "Full Council Meetings"

_SPECIAL = re.compile(r"special", re.IGNORECASE)


@register_scraper
class UnleyScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 59 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 59

    list_name = _LIST_NAME
    papers_by = "heading"
    # Each year-filtered page carries the full year dropdown, so production
    # skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__("unley", "SA", f"{_BASE}/Full-Council-Meetings")

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [Listing(f"{_BASE}/Council-assessment-panel", _LIST_NAME)]

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        if row.meeting_type != "Full Council":
            return row.meeting_type or self.default_name
        if any(_SPECIAL.search(url.rsplit("/", 1)[-1]) for url in papers.values()):
            return "Special Council Meeting"
        return "Council Meeting"
