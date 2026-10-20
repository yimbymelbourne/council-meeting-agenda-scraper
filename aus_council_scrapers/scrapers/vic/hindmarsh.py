"""Hindmarsh Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is the Council Meetings page itself (``OC CL Public Meetings``).
The year filter offers 2017–2026; 2020 onwards is fetched.

Papers sit under ``<h3>Agenda</h3>``, ``<h3>Attachments</h3>`` and
``<h3>Minutes</h3>`` with every link "Download PDF", so
`papers_by = "heading"`. Below them a Related Information list carries the
item attachments, among them the previous meeting's minutes and committee
minutes ("item-4-attachment-1-…-minutes-council-meeting…"); heading mode
never reads that list while the payload has headings. Some filenames carry a
date a few days off the meeting (the 23 October 2024 agenda is
"2024_10_17-agenda-…"); dates come from the listing row.

Types are Ordinary, Special and Statutory Meeting, all of Council, so nothing
is filtered. One production year is one listing page (pagesize=100) plus one
payload per meeting: 11 requests for 2026.

The site is on Granicus's Akamai edge, like the other OpenCities councils. A
bare request with only a User-Agent got a 403 in the October 2026 scout; on
20 October 2026 the same request, and `DefaultFetcher`, both got a 200.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class HindmarshScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 21 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 21

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "hindmarsh",
            "VIC",
            "https://www.hindmarsh.vic.gov.au/Council/Council-Meetings",
        )
        self.default_name = "Council Meeting"
