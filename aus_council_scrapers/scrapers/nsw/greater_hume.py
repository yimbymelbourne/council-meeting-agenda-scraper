"""Greater Hume Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds the Ordinary and Extraordinary
Council meetings, about one a month, back to 2018; upcoming meetings appear
once their agenda is up.

Papers are filed under headings that name the meeting after the paper—
"Agenda - Ordinary Meeting 23 April 2025", "Agenda and Annexures - Ordinary
Meeting 16 September 2026", "Minutes - Ordinary Meeting …"—so
``papers_by = "heading"``. The base class anchors "Agenda" and "Minutes" at
the start of the heading, which passes over "Annexures 1-10 - …", "Addendum -
…" and "Addendum Report to the Ordinary Meeting". "Agenda and Annexures" is
one PDF with the annexures bound in, which is still the agenda.

The filter also offers Special Meeting and Youth Committee Meeting types. No
Special Meeting is listed from 2020 on, and a Youth Committee is not a body
this project watches, so the allowlist keeps Council meetings only: each row
kept costs a payload request.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per meeting: 10 for 2026.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class GreaterHumeScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 17 s for
    # 10 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 17

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(r"\b(?:ordinary|extraordinary|special)\b", re.IGNORECASE)
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "greater_hume",
            "NSW",
            "https://www.greaterhume.nsw.gov.au/Your-Greater-Hume-Council/Council-Meetings",
        )
