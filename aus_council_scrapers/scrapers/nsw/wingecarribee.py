"""Wingecarribee Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list holds every Council meeting back to 2019, including those held
under the administrator (2021–2024); upcoming meetings appear once their
agenda is up. Its internal name is "Council Meeting - OC CL Public
Meetings", read off the form ``action`` after a year-filter postback. The
four standard names are ignored by the site, which is why the site was first
scouted as needing a postback; with the real name the ``dlv_`` URL filters
by year like any other.

The filter offers sixteen meeting types: the Council's own, the Local
Planning Panel and its predecessor (the Independent Advisory Planning
Assessment Panel), and advisory committees—Finance, Traffic, Heritage,
Floodplain and others. From 2020 only Ordinary and Extraordinary Council
meetings are listed. The allowlist keeps the Council's meetings and the
planning panels, so that if the committees start publishing here they cost
nothing: each row kept is a payload request.

Papers are filed under headings—"Agenda" or "Agenda - 7 August 2024",
"Minutes", "Draft Minutes"—with every link labelled "Download PDF", so
``papers_by = "heading"``. Attachments under separate cover, addenda and
supplementary agendas are in the Related Information list, which heading
mode does not read.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per meeting: 10 for 2026.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class WingecarribeeScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 19 s for
    # 10 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "Council Meeting - OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(
        r"\b(?:ordinary|extraordinary|special|council meeting|planning)\b",
        re.IGNORECASE,
    )
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "wingecarribee",
            "NSW",
            "https://www.wsc.nsw.gov.au/Council/Council-Meetings/Council-Meeting-Minutes-and-Agendas",
        )
