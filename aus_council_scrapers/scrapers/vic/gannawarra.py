"""Gannawarra Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Agendas and Minutes" (``OC CL Public Meetings``). The year
filter offers 2013–2026; 2020 onwards is fetched.

Papers sit under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>``, with links
labelled "Download Agenda" and "Download Minutes", so
`papers_by = "heading"`. The Agenda section sometimes carries a second file
after the agenda—"Attachments Under Separate Cover" (2020, 2023), an urgent
late item (20 March 2024)—which heading mode passes over.

Two meetings on one day are two listing rows, and stay two records: an
Ordinary and a Special Meeting on 19 November 2025 (the Special one elected
the Mayor), and again on 21 October 2026. Types are Ordinary, Special and
Unscheduled Meeting, all of Council, so nothing is filtered. One production
year is one listing page (pagesize=100) plus one payload per meeting: 11
requests for 2026.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class GannawarraScraper(OpenCitiesMeetingsScraper):
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
            "gannawarra",
            "VIC",
            "https://www.gannawarra.vic.gov.au/Your-Council/Council-Meetings/Agendas-and-Minutes",
        )
        self.default_name = "Council Meeting"
