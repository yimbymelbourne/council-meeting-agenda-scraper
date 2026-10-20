"""Surf Coast Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Council Meetings,
Unscheduled and Special Council Meetings, and the Special Council Meetings
for Hearing Submissions. All are meetings of the council, so nothing is
filtered out.

**Since May 2022 a past meeting keeps only its minutes.** Every payload
from 24 May 2022 on has minutes and no agenda, apart from 14 November 2024;
meetings up to April 2022 still have both. So the history here is mostly
minutes-only. That is the council's choice, not a
parsing gap. The minutes are often very large (117 MB for 22 September 2026)
because they carry the reports and attachments.

Papers are filed two ways, and neither base mode reads both:

* Older payloads, and a few newer ones, are a flat list labelled by filename:
  "2022-04-26-Council-Meeting-Agenda.pdf".
* Newer ones file each paper under a heading, with a link labelled "Download
  Minutes" or "Download Agenda"—or, on 28 October 2025, a heading of
  "Council Meeting - 28 October 2025 - Minutes" and a link labelled only
  "Download PDF". Heading mode wants the heading to start with "Minutes", and
  it reads only the first link in a section, which loses the minutes filed
  under the Agenda heading of 14 November 2024.

So `papers` gives each link labelled only "Download PDF" its section's
heading as a label, and then reads every link by its label (link-text mode).
Council resolutions on single items, items released from confidential
sessions and attachment books are passed over.

**The year filter drops meetings, so the listing is paged instead.** The
council leaves some rows out of every year: the 25 August 2026 Council
Meeting, which has its minutes online, is on the unfiltered listing and on
no ``(dd_OC Year=N)`` page (checked 20 Oct 2026; every other row of 2019–2027
is on its year's page). So the main listing is ``by_year=False``: read
newest first, 50 rows a page, until a page reaches back before the wanted
year. Page 1 runs from September 2026 back to July 2023, so production's one
year is one listing request; the full history from 2020 is three.

One production year is the listing page and a payload per meeting: 11
requests for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import Listing, _in_nested_attachments, _label
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)

# "Download PDF (96MB)": the size is part of the link text.
_GENERIC = re.compile(r"^download(?:\s+pdf)?\s*(?:\(.*\))?$", re.IGNORECASE)


@register_scraper
class SurfCoastScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    papers_by = "link_text"

    def __init__(self):
        super().__init__(
            "surf_coast",
            "VIC",
            "https://www.surfcoast.vic.gov.au/About-us/Council/Council-Meetings/Minutes-Agendas",
        )

    def main_listing(self) -> Listing:
        # by_year=False ignores page_size, so the page size rides in the
        # listing's filters: "(pagesize=50)", then "(pagesize=50)(pageindex=2)".
        return Listing(
            self.listing_url,
            self.list_name,
            filters=f"(pagesize={self.page_size})",
            by_year=False,
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for section in content.find_all("div", class_="meeting-document"):
            heading = section.find("h3")
            if not heading:
                continue
            for anchor in section.find_all("a", href=True):
                if _in_nested_attachments(anchor, section):
                    continue
                if _GENERIC.match(_label(anchor.get_text(" ", strip=True))):
                    anchor.string = heading.get_text(" ", strip=True)
        return super().papers(content)
