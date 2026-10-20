"""Moyne Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Council meetings minutes and agendas"
(``OC CL Public Meetings``); its parent, ``.../Council-Meetings``, is a
landing page. The council keeps only about the last 12 months online and
gives older papers on request (the page says so), so the history is rolling:
rows exist from April 2024, and the 2013–2023 options in the year filter
return nothing.

Each payload is one flat Related Information list labelled "Agenda (PDF,
19MB)", "Minutes", "Confirmed minutes" or "Unconfirmed minutes", so
`papers_by = "link_text"`. Every one of the 36 meetings recorded in October
2026 has both an agenda and minutes. Meeting types are Ordinary and Special,
both Council meetings, so nothing is filtered.

One production year is one listing page (pagesize=100) plus one payload per
meeting: 12 requests for 2026.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MoyneScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 23 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 23

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "moyne",
            "VIC",
            "https://www.moyne.vic.gov.au/Your-council/Council-and-councillors"
            "/Council-Meetings/Council-meetings-minutes-and-agendas",
        )
        self.default_name = "Council Meeting"
