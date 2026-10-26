"""Horsham Rural City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting: Council Meetings
(Ordinary Meetings early in 2020), the annual Statutory Meeting and one
Delegated Committee of Council meeting (2022). All are meetings of the
council, so nothing is filtered out.

Papers are filed under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>`` (or
"Unconfirmed Minutes"), so ``papers_by = "heading"``. The links say "Download
PDF", or "Download Agenda" and "Download Minutes" in 2020, and link-text mode
would miss the agenda. The agenda under the heading includes its appendices
("…-inc-appendices-…"); the separate appendices-only file sits in the
Related Information list, which heading mode does not read.

The site gives one time as 05:30 AM (22 June 2020) where every other meeting
is at 5:00 or 5:30 PM; it is reported as the site gives it.

One production year is the listing page and a payload per meeting: 12
requests for 2026.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)


@register_scraper
class HorshamScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 24 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    papers_by = "heading"

    def __init__(self):
        super().__init__(
            "horsham",
            "VIC",
            "https://www.hrcc.vic.gov.au/Our-Council/Inside-Council/Council-Minutes-and-Agendas",
        )
