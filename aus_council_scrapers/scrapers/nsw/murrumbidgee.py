"""Murrumbidgee Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary
meetings, upcoming ones included, with a year filter. Its filter offers 2018,
2021 and 2023–2026 only, and 2021 holds a single meeting whose one link is a
bare GUID labelled "February 2021 - Ordinary Meeting"; it says neither
agenda nor minutes, and as ``/files/<guid>/`` it is a 404, so it is not a
file at all. In practice the history starts in 2023.

Most payloads are one flat "Related Information" list labelled by link text:
"September 2026 Council Meeting - Business Paper", "... - Mayoral Report",
"... - Attachments", "... Minutes". A few early-2024 payloads file the papers
under headings instead—"March 2024 Business Paper", "Attachments",
"Minutes"—beside a Related Information list holding unrelated documents
("Draft Long Term Financial Plan 2024-2033"). So ``papers_by = "heading"``:
it reads the headings where there are some and falls back to link text
where there are none. Either way the business paper is the agenda; the
January 2024 extraordinary meeting has an "Agenda" too, and the business
paper outranks it.

One production year is 9 requests: the listing filtered to that year (8
meetings in 2026) and a payload per meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MurrumbidgeeScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 16 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 16

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # The busiest year is 13 meetings: one listing page a year.
    page_size = 50
    # The year-filtered page offers every year (checked 20 October 2026).
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "murrumbidgee",
            "NSW",
            "https://www.murrumbidgee.nsw.gov.au"
            "/My-council/Council-meetings/Meeting-documents-recordings",
        )
