"""Wujal Wujal Aboriginal Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Special meetings,
and only from 2026: the year filter offers 2018 too, and it returns no
rows. Every row is a meeting of Council, so nothing is filtered out.

Most payloads are one flat Related Information list labelled by filename
("20260915-WWASC-Ordinary-Council-Meeting-Agenda.pdf",
"20260915-Appendices-COMBINED.pdf", "20260915-CONFIRMED-WWASC-Ordinary-
Council-Meeting-MINUTES.pdf"), but 28 April 2026 files its papers under
headings ("28.4.2026 Ordinary Council Meeting Agenda", "... Appendices",
"28.4.2026 Minutes") with "Download PDF" links. ``papers_by = "search"``
reads both: the headings by the word they contain, and a payload with no
headings by its list's link text. The appendices books are not the agenda.

Some links are a bare GUID (15 September 2026's minutes, 20 January 2026's
appendix), which the base class rebuilds as ``/files/<guid>/<name>.pdf``;
that returns the PDF (checked 20 October 2026).

robots.txt disallows only gallery, training and unused paths. The site is
behind Akamai; the project fetcher gets 200 where a minimal client gets
Akamai's "Access Denied".

One production year is 14 requests: the listing filtered to that year at
``page_size`` 50 (13 rows in 2026), then a payload per meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class WujalWujalScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 28 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    list_name = "OC CL Public Meetings"
    papers_by = "search"
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "wujal_wujal",
            "QLD",
            "https://www.wujalwujalcouncil.qld.gov.au"
            "/Council/Council-Meetings-and-Agenda/Agenda-and-Minutes",
        )
