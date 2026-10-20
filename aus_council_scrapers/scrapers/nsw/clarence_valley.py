import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class ClarenceValleyScraper(ResolveScraper):
    # Clarence Valley (NSW) is the `clarence` tenant; the `clarence` slug is
    # Clarence City in Tasmania. Its website frames the tenant's /web/
    # portal. The tenant holds Council meetings back to 2015. The API marks
    # everything before June 2019 unpublished, but that is all before
    # EARLIEST_YEAR, so it is never asked for.
    tenant = "clarence"

    # Council only; extraordinary meetings are typed Ordinary Council too.
    # Left out are Presentations & Deputations, where residents address
    # councillors before a meeting, and the Briefing Committee, which
    # decides nothing.
    meeting_types = re.compile(r"^Ordinary Council$")

    # The late items for the 26 March 2024 meeting, entered as an event of
    # their own an hour after it. Kept, they would be a second Ordinary
    # Council meeting that day with a supplementary paper as its agenda.
    skip_events = frozenset({641})

    # Event 81, "Ordinary Council Meeting - 17 April 2025 (Rescheduled)", is
    # left on the tenant's date, 24 April 2025 at 3pm, and not moved to 17
    # April through `event_dates`. Its business paper is for 17 April at
    # 11:30am, but the meeting opened then and adjourned at 11:50am, and its
    # minutes are headed 24 April, the day it resumed. The tenant and the
    # council's own name for the event both treat it as moved to that day,
    # and `event_dates` would pair the 17 April date with the 3pm time of
    # the resumed sitting.

    # Not `include_unpublished`, although the /web/ portal lists the two
    # past Council events the API marks unpublished—the 14 March 2025 and 23
    # September 2026 extraordinary meetings—with their agenda and minutes.
    # Learning which of their documents exist means asking DocPreview on
    # clarence.resolve.red, and that host's robots.txt is `Disallow: /`. So
    # those two meetings are left out.

    def __init__(self):
        super().__init__("clarence_valley", "NSW")

    def _meeting_name(self, event: dict) -> str:
        name = super()._meeting_name(event)
        # The base class finds a special meeting by the word in the event
        # name, and the 18 February 2025 one is "Extrordinary Council
        # Meeting".
        if name == "Ordinary Council" and _MISSPELT_EXTRAORDINARY.search(
            event.get("name") or ""
        ):
            return "Extraordinary Council"
        return name


_MISSPELT_EXTRAORDINARY = re.compile(r"\bext\w*ordinary\b", re.IGNORECASE)
