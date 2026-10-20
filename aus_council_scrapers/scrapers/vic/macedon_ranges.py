"""Macedon Ranges Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2018 with a
year filter, upcoming ones included: Council's Scheduled, Unscheduled and
Special Meetings (Ordinary Meetings in earlier years), the Planning
Delegated Committee, the Submitters (Delegated) Committee and Section 223
submission hearings. Each row costs a payload request, so ``meeting_types``
keeps the meetings of Council and the Planning Delegated Committee—the
bodies that decide—and drops the committees that only hear submissions.

Papers are filed under headings that lead with the date, "23 September
2026 Agenda" and "23 September 2026 Minutes (DRAFT)", which heading mode
strips before matching (``papers_by = "heading"``). Each agenda section's
first file is the agenda; its attachments follow it in a folder of their
own.

robots.txt (3,122 lines, almost all staff and news pages) disallows nothing
this requests. The site answers the project's identifying User-Agent with
200; the scout found a browser User-Agent refused with 403, so the default
stays.

One production year is 11 requests at most: the listing filtered to that
year at ``page_size`` 50 (11 rows in 2026, one of them a Submitters
Committee), then a payload per kept meeting.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MacedonRangesScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 21 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 21

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(
        r"^(?:scheduled|unscheduled|special|ordinary|extraordinary)\s+(?:council\s+)?meeting"
        r"|\bplanning\b",
        re.IGNORECASE,
    )
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "macedon_ranges",
            "VIC",
            "https://www.mrsc.vic.gov.au/About-Council/Our-Council/Council-Meetings/Agendas-and-Minutes",
        )
