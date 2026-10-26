"""Melton City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting. Paging inside a
filtered year is a plain GET (``(pageindex=N)``), verified on 2025's two
pages. The listing seems to show a meeting only once its papers are up: in
October 2026 the newest row was 28 September 2026, with no later meeting
listed ahead of time.

Papers are filed under headings—"Agenda", "Minutes", and a "Live Stream"
section linking the webcast—with each paper labelled "Download PDF", so
``papers_by = "heading"``. Through 2022 the agenda heading was "Agenda with
attachments"—one file, the agenda with its appendices bound in—which the
base class takes as the agenda. Item appendices otherwise sit in the separate
Related Information list, which heading mode ignores. A few meetings have an
empty Agenda or Minutes heading (10 May 2021, 7 June 2021), and the 26 March
2020 meeting published a "Record of Meeting" in place of minutes; those are
reported without the missing paper.

Meeting types are Melton's own: "Scheduled Meeting" is the regular Council
meeting, "Unscheduled Meeting" an extra one, plus Special, Statutory and (in
2020) Ordinary meetings. The filter also offers Committee and Section 223
Committee meetings, which have no rows since 2020; the allowlist keeps them
out should they reappear, since each listed meeting costs a payload request.
One production year is the unfiltered page, one or two filtered pages and one
payload per meeting: 10 requests and 20 s for 2026, measured in October 2026.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MeltonScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 19 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(
        r"^(?:(?:un)?scheduled|special|statutory|ordinary|annual general)?\s*meeting$",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__(
            "melton",
            "VIC",
            "https://www.melton.vic.gov.au/Council/About-Council/Minutes-Agendas",
        )
