"""Liverpool Plains Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The council's "Business papers and minutes" page has no meetings on it; it
links this "Archived business papers and minutes" listing, which says it
covers February 2024 to February 2026 but in October 2026 was still being
updated, to 14 September 2026. One list (``OC CL Public Meetings``) holds
Ordinary and Extraordinary meetings of the Council and nothing else. The
``dlv_`` year filter offers 2018 and 2024–2026; each of 2024–2026 returned
only its own rows. Older papers are available only by GIPA request, the
council's page says.

The council also publishes through Resolve (tenant ``liverpoolplains``) from
25 March 2026. In October 2026 Resolve held the same seven Ordinary Council
meetings from March to September 2026 as this listing, plus a Public Forum,
while this listing also has February 2026. So this listing is read alone.
If the council stops updating it, the current year should move to Resolve
(``ResolveScraper`` with ``resolve_from``) and this listing become the
archive.

Papers are filed under headings—"Business Paper", "Minutes"—each paper a
"Download PDF" link. The heading rules only know the word "Agenda", so
`papers` reads "Business Paper" as the agenda heading; see there.

robots.txt disallows ``/Council/Council-meetings/Agendas-and-minutes``, an
older, unused path; this listing is not under it.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=50)`` page held all 14 of 2025's rows, and the filtered page
carries the full year dropdown. A production year is one listing request
plus one payload per meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# "Business Paper" is this council's word for the agenda. Heading mode
# anchors "Agenda" at the start of the heading, so the heading is renamed
# before it is read. Only the exact phrase is touched, so a heading such as
# "Business Paper Attachments" would become "Agenda Attachments" and still
# be passed over as an attachment book.
_BUSINESS_PAPER = re.compile(r"^\s*business\s+papers?\b", re.IGNORECASE)


@register_scraper
class LiverpoolPlainsScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 9
    # requests (one listing page and 8 payloads), 16 s. Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 16

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "liverpool_plains",
            "NSW",
            "https://www.liverpoolplains.nsw.gov.au/Council/Council-meetings/"
            "Archived-business-papers-and-minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            renamed = _BUSINESS_PAPER.sub("Agenda", text, count=1)
            if renamed != text:
                heading.string = renamed
        return super().papers(content)
