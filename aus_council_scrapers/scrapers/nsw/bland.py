"""Bland Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Special meetings from
2012, upcoming ones included, with a year filter. Those are the only two
meeting types, so nothing is allowlisted.

Papers are one flat "Related Information" list, so ``papers_by =
"link_text"``. The agenda is only ever called the business paper—"Business
Paper September 2026", "Business-Paper-December-2023.pdf",
"BUSINESS-PAPER-November-2021.pdf"—which the base class reads as the agenda.
Beside it sit "Business Paper Extra Attachments" or "Attachments for
December 2025 Business Paper", which are attachment books and are passed
over. Minutes are "Minutes September 2026 Unconfirmed", "July 2026 Meeting
Minutes", "CONFIRMED-MINUTES-DEC-2023-COUNCIL.pdf". Audio recordings (.mp3,
.mp4) share the list and are not papers.

The 20 October 2026 business paper is linked by a bare GUID
(``href="e02abdf0-..."``), which resolves to a 403 against the page; the
base class rebuilds it as ``/files/<guid>/Business-Paper-October-2026.pdf``,
which returns the PDF.

One production year is 11 requests: the listing filtered to that year (10
meetings in 2026) and a payload per meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class BlandScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 19 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    # The busiest year since 2020 is 13 meetings: one listing page a year.
    page_size = 50
    # The year-filtered page offers every year (checked 20 October 2026).
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "bland",
            "NSW",
            "https://www.blandshire.nsw.gov.au/Council/Council-Meetings",
        )
