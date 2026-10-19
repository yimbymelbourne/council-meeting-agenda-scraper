"""Hume City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing moved to ``/Agendas-Minutes-and-Meeting-Recordings``; the
``...-and-Audio-Recordings`` address in docs/councils.md now 302s here. Its
list is ``HCC CL Public Past Meetings``—a council-prefixed name the
``OC CL Public Meetings`` default would silently miss, since the site serves
an unknown list name the unfiltered page. Paging inside a filtered year is a
plain GET (``(pageindex=N)``), verified on the three pages of 2025.

The page has two blocks: "Next Meeting", holding only the next meeting (26
October 2026 when this was written), and "Previous Meetings", the filtered
list. The Next Meeting block is repeated on every page of every year's
filter, so the base class leaves it out when checking the filter held and
de-duplicates it on its cvid. Before its agenda is published that meeting's
payload holds only a time and a map link, and it is skipped until it has one.

The main listing starts at the November 2020 election. The term before it
sits under "Previous Council Term – Agenda and Minutes", a page per year
running the same module under another list name (``Template for all past
meetings``). Only its 2020 page adds anything: measured in October 2026, the
2021 and 2022 pages hold the same meetings (same cvids) as the main listing,
and the 2020 page adds the seventeen meetings from 10 February to 12 October
2020. So that one page is read as an extra listing, and only when 2020 is
wanted—production, asking for the current year, never fetches it. 10
August 2020 published its minutes (listed twice) and no agenda.

Papers are one flat "Related Information" list labelled by filename—
"AGENDA-12-October-2026-Open.pdf (PDF, 4MB)",
"MINUTES-12-October-2026-Open.pdf (PDF, 303KB)"—beside a YouTube recording
link, so ``papers_by = "link_text"``. The hyphens are word boundaries, so
``\\bagenda\\b`` reads these as they are.

One meeting labels its agenda by the meeting's name alone: the 3 October 2023
Joint Council Meeting (with Whittlesea and Mitchell, held at South Morang)
lists one paper, "Joint Council Meeting 3-October-2023.pdf", whose first page
reads "Agenda Joint Council Meeting Tuesday 3 October 2023". A payload whose
only PDF is named after a council meeting and is filed in the council's
``/council-meetings/agendas/`` folder is therefore taken as the agenda. Both
tests are needed: Hume labels every set of minutes "MINUTES-...", but one
minutes file in the history does sit in the agendas folder.

Meeting types are Ordinary, Ordinary (Town Planning), Statutory, Special,
Committee of the Whole Council and Joint Council Meeting. All are meetings of
the Council, so nothing is allowlisted.

Hume meets roughly fortnightly, so one production year costs slightly more
than the 20-request target: the unfiltered page, two filtered listing pages
and one payload per meeting—22 requests and 41 s for 2026, measured in
October 2026. Cutting it would mean dropping Ordinary meetings, which are the
point.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    Listing,
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
)

_PREVIOUS_TERM_2020 = (
    "https://www.hume.vic.gov.au/Your-Council/Governance"
    "/Previous-Council-Term-–-Agenda-and-Minutes/2020-Council-Agenda-and-Minutes"
)
_NAMED_FOR_MEETING = re.compile(r"\bcouncil\s+meeting\b", re.IGNORECASE)
_AGENDAS_FOLDER = re.compile(r"/council-meetings/agendas/", re.IGNORECASE)


@register_scraper
class HumeScraper(OpenCitiesMeetingsScraper):
    list_name = "HCC CL Public Past Meetings"
    papers_by = "link_text"

    def __init__(self):
        super().__init__(
            "hume",
            "VIC",
            "https://www.hume.vic.gov.au"
            "/Your-Council/Council-Meetings/Agendas-Minutes-and-Meeting-Recordings",
        )

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            Listing(
                _PREVIOUS_TERM_2020,
                "Template for all past meetings",
                years=frozenset({2020}),
            )
        ]

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers = super().papers(content)
        if papers:
            return papers
        pdfs = [a for a in content.find_all("a", href=True) if _is_pdf(a["href"])]
        if len(pdfs) == 1:
            href = pdfs[0]["href"].strip()
            label = _label(pdfs[0].get_text(" ", strip=True))
            if _NAMED_FOR_MEETING.search(label) and _AGENDAS_FOLDER.search(
                urlparse(href).path
            ):
                return {"agenda": urljoin(self.base_url, href)}
        return papers
