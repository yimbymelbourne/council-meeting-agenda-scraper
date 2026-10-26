"""Mount Isa City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Special meetings
(and the 5 April 2024 Post Election Council Meeting) with a year filter
offering 2018 and 2023 onward. 2018 returns no rows, so the history starts
in 2023. Every row is a meeting of Council, so nothing is filtered out.

Each payload is one flat Related Information list—"Agenda (PDF, 20MB)",
"Agenda Item 10.3 Attachments", "Unconfirmed Minutes", "Confirmed
Minutes"—so ``papers_by = "link_text"``. Some minutes links are a bare
GUID with "Minutes" as the text (23 September and 26 August 2026), which the
base class rebuilds as ``/files/<guid>/Minutes.pdf``; both return the PDF
(checked 20 October 2026, although the scout found the GUID alone 404s).

24 April 2024's minutes are labelled "Unconfirmed Minute", which
``\\bminutes\\b`` does not match, and the singular is otherwise how a
mayoral minute is named. A minute qualified as confirmed or unconfirmed is
the meeting's minutes, so that label is read as plural (`papers`).

The page also links "YYYY COMBINED Unconfirmed Ordinary Meeting Minutes"
PDFs for 2014–2022, one per year. They cannot be split into meetings, so
they are not read.

robots.txt disallows nothing on the meeting paths. The site is behind
Akamai (``x-akamai-transformed``); the project fetcher gets 200.

One production year is 11 requests: the listing filtered to that year at
``page_size`` 50 (10 rows in 2026), then a payload per meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_QUALIFIED_MINUTE = re.compile(r"\b((?:un)?confirmed\s+)minute\b", re.IGNORECASE)


@register_scraper
class MountIsaScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "mount_isa",
            "QLD",
            "https://www.mountisa.qld.gov.au/City-Council/Council/Council-Meetings/Agendas-and-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for anchor in content.find_all("a", href=True):
            for text in anchor.find_all(string=_QUALIFIED_MINUTE):
                text.replace_with(_QUALIFIED_MINUTE.sub(r"\1minutes", text))
        return super().papers(content)
