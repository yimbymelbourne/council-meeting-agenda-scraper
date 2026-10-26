"""Central Goldfields Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Special meetings of
Council with a year filter offering 2018 onward. Those are the only meeting
types, so nothing is filtered out. The years before 2022 carry little:
2021's three rows hold only a link to the meeting's video, so they are
skipped as meetings with no papers.

Headings put the date and the meeting before the word—"22 October 2025
Council Meeting Agenda", "17 December 2025 Confirmed Council Meeting
Minutes", "26 November Council Meeting Agenda", "Council Meeting Agenda 17
December 2025"—so ``papers_by = "search"`` looks for "agenda" or
"minutes" anywhere in the heading.

A few meetings file one of their papers only in the Related Information
list, labelled by filename: 19 November 2025's statutory meeting has its
agenda there ("Statutory-Council-Meeting-Agenda-19-November-2025.pdf") and
23 July 2025 its minutes. ``related_fills_gaps`` takes a paper the headings
lack from that list. A paper the headings already give is never replaced
from it: 30 April 2025 lists a second copy of its agenda and the
unconfirmed minutes there, beside the confirmed minutes under a heading.

The listing's 28 September 2026 row is an additional Council meeting
("28 September 2026 Additional Council Meeting Agenda"), listed as an
Ordinary Meeting five days after the 23 September one.

robots.txt has no disallow rules for this site's paths.

One production year is 10 requests: the listing filtered to that year at
``page_size`` 50 (9 rows in 2026), then a payload per meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class CentralGoldfieldsScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "OC CL Public Meetings"
    papers_by = "search"
    related_fills_gaps = True
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "central_goldfields",
            "VIC",
            "https://www.centralgoldfields.vic.gov.au/About-Us/Council-Information/Council-Meetings",
        )
