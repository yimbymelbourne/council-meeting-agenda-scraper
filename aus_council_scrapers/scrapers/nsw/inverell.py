import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper

# A Public Forum entered under a Council meeting type, which the type filter
# cannot catch.
_FORUM = re.compile(r"\s*(public|open) forum\b", re.IGNORECASE)


@register_scraper
class InverellScraper(ResolveScraper):
    # Inverell moved to Resolve for its 30 October 2024 meeting; the tenant
    # holds nothing earlier. Business papers from about 2017 to 2024 are on
    # the council's WordPress archive page
    # (https://inverell.nsw.gov.au/your-council/business-papers-minutes-council-meetings/meeting-archives/),
    # which this scraper does not read.
    tenant = "inverell"

    # Council meetings, and the Strategy and Policy Committee (from August
    # 2026): every councillor sits on it, and it takes the strategic reports
    # (residential land drainage, asset programs) that then go to Council.
    # The tenant's other type is the Public Forum, which decides nothing.
    # Three committee meetings a year cost three detail calls.
    meeting_types = re.compile(
        r"^(Ordinary Council Meeting|Strategy and Policy Committee)$"
    )

    def __init__(self):
        super().__init__("inverell", "NSW")

    def _record(self, event, today):
        # The 22 April 2026 Public Forum is filed under Ordinary Council
        # Meeting. Checked by name before the detail call, so it costs
        # nothing.
        if _FORUM.match(event.get("name") or ""):
            return None
        return super()._record(event, today)
