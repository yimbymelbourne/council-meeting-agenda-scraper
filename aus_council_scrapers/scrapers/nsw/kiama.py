"""Kiama Municipal Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary Council
meetings back to 2014; upcoming meetings appear once their agenda is up.

Papers are one flat "Related Information" list labelled by link text—
"Agenda - 15 September 2026", "Enclosures - …", "Supplementary - …",
"Minutes - …", "Minutes attachment - …", "Minutes as amended - …"—so
``papers_by = "link_text"``. The base class passes over the enclosures,
supplementary papers and minutes attachments. 14 December 2023 labels its
minutes "Minute as amended", singular, which the base class's ``minutes\b``
rule passes over, so `papers` rewrites that label to the plural first. The
plural "Minutes as amended" is ranked below plain "Minutes" by the base
class, as an amended paper. The singular is otherwise a mayoral minute
("Mayoral Minute - …"), and those never start the label.

Two of the filter's types are left out (``meeting_types``). "Special
Meeting" holds only Kiama's Youth Engagement meetings (27 August 2020, 5
August 2021)—not Council meetings; the council's own special meetings are
filed as "Extraordinary Meeting". "Public Access" is the session where
residents address councillors, with no rows from 2020 on.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per meeting: 13 for 2026.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_MINUTE_AS_AMENDED = re.compile(r"^\s*minute(?=\s+as\s+amended\b)", re.IGNORECASE)


@register_scraper
class KiamaScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 24 s for
    # 13 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    meeting_types = re.compile(r"^(?:Ordinary|Extraordinary) Meeting$", re.IGNORECASE)
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "kiama",
            "NSW",
            "https://www.kiama.nsw.gov.au/Council/Council-meetings/Agendas-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for anchor in content.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True)
            tidied = _MINUTE_AS_AMENDED.sub("Minutes", label, count=1)
            if tidied != label:
                anchor.string = tidied
        return super().papers(content)
