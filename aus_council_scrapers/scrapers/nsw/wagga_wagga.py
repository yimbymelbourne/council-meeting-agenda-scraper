import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# The venue line under the meeting type sometimes holds a meeting description
# instead: "Ordinary Council Meeting" on 16 of the 2024 Council rows, and
# "Extraordinary - E-Meeting" on one 2020 Traffic Committee row.
_NOT_A_VENUE = re.compile(r"^(?:Ordinary|Extraordinary)\b", re.IGNORECASE)


@register_scraper
class WaggaWaggaScraper(InfoCouncilScraper):
    # Self-hosted InfoCouncil. The listing URL must be /Default.aspx, not the
    # bare root: robots.txt there is "Disallow: /" with exceptions for "/$",
    # "/Default.aspx", "/RedirectToDoc.aspx" and "/Open", so "/?year=2026" is
    # off limits while "/Default.aspx?year=2026" is allowed. The base class
    # appends "?year=" to this URL as given, and resolves the RedirectToDoc
    # links against it to the same host.
    #
    # The committee cell carries the venue ("Council Meeting Room"), and late
    # items get rows of their own ("Council Meeting - Late Items", filed as
    # _AT_SUP), so the tidy flag is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "wagga_wagga",
            "NSW",
            "https://www.wagga.nsw.gov.au",
            "https://meetings.wagga.nsw.gov.au/Default.aspx",
        )

    def scraper(self) -> list[ScraperReturn]:
        meetings = super().scraper()
        for meeting in meetings:
            if meeting.location and _NOT_A_VENUE.match(meeting.location):
                meeting.location = None
        return meetings
