"""Rockhampton Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2016, and its
year filter is exact: the per-year counts add up to the unfiltered listing's
371 results (checked 20 October 2026). The listing honours ``(pagesize=N)``,
so a year is one listing request (50 rows in 2022 and 2026, the busiest).

Papers are filed under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>`` with
every link labelled "Download PDF", so ``papers_by = "heading"``. The other
heading seen is "Agenda Supplementary" (late items), which the base class
passes over.

The listing mixes Council with its standing committees: Infrastructure,
Communities, and from 2026 Economic Development and Rockhampton Airport.
Only Ordinary and Special Council Meetings are fetched (`meeting_types`).
Each meeting is a payload request of its own, and the committees—none of
them named as a planning body—would add about 18 requests a year. Even so
one production year is large: 2026 has 18 ordinary and 14 special meetings,
so about 33 requests.

robots.txt lists about 800 retired sub-pages of the listing
(".../12-July-2022-Ordinary-Council-Meeting/Agenda"); it disallows neither
the listing, its query strings, nor ``OCServiceHandler.axd``. The site is
behind Akamai (``Server-Timing: ak_p``), which served the identifying
User-Agent without a challenge from a home IP; it has not been measured from
a GitHub runner.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_COUNCIL = re.compile(r"^(?:Ordinary|Special) Council Meeting$")


@register_scraper
class RockhamptonScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 65 s
    # (33 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 65

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = _COUNCIL

    def __init__(self):
        super().__init__(
            "rockhampton",
            "QLD",
            "https://www.rockhamptonregion.qld.gov.au/AboutCouncil/Meeting-Agendas-and-Minutes",
        )
