"""Frankston City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Frankston splits its meetings across two OpenCities lists:

* **Past**—``OC CL Public Past Meetings`` at
  ``/Past-Council-Meeting-Agendas-and-Minutes``, back to January 2017.
* **Upcoming**—``OC CL Public Upcoming Meetings`` at
  ``/Upcoming-Council-Meeting-Agendas-<year>``. The URL carries the year and
  the council moves it: the ``-2024`` address once recorded in
  docs/councils.md now 302s to ``-2026``. So it is not hard-coded but read off
  the Past page's own navigation, which links to the current one.

A meeting sits on the upcoming list until it is held, which is when its agenda
is published, so the upcoming list is where a new agenda first appears. In
October 2026 its four rows (26 October to 7 December) had no papers yet; they
are fetched anyway, and skipped until they do.

Papers are one flat "Related Information" list labelled by link text—
"CM09 - 3 August 2026 - Agenda", "... - Supporting Attachments",
"... - Draft Minutes", "... - Final Minutes"—so ``papers_by = "link_text"``,
which keeps the final minutes over the draft when both are listed. Labels
from 2020 are bare filenames with underscores—"OM3_-_10_March_2020_Agenda.pdf"
(10 March 2020)—which the base class reads as spaces. The Past
page also links a "Minute Index" PDF per year; those are outside the listing
rows and never read.

Meeting types are only "Council Meeting" (and "Ordinary Meeting" before 2021)
and "Special Meeting", so there is nothing to allowlist. One production year
is the two list pages, three or four filtered listing pages and one payload per
meeting: about 20 requests.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import Listing, OpenCitiesMeetingsScraper

_LISTING_URL = (
    "https://www.frankston.vic.gov.au"
    "/Council/Council-and-committee-meetings/Past-Council-Meeting-Agendas-and-Minutes"
)

_UPCOMING_PATH = re.compile(
    r"/Council/Council-and-committee-meetings/Upcoming-Council-Meeting-Agendas-\d{4}/?$",
    re.IGNORECASE,
)


@register_scraper
class FrankstonScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 40 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 40

    list_name = "OC CL Public Past Meetings"
    papers_by = "link_text"

    def __init__(self):
        super().__init__("frankston", "VIC", _LISTING_URL)

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        soup = BeautifulSoup(first_page_html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = urljoin(self.listing_url, anchor["href"].strip())
            if _UPCOMING_PATH.search(url.split("?")[0]):
                return [Listing(url, "OC CL Public Upcoming Meetings")]
        self.logger.warning(
            "No link to the upcoming-meetings page on the Past listing; "
            "agendas for meetings not yet held will be missed."
        )
        return []
