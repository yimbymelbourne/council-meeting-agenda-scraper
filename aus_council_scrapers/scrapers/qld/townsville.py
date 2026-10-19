import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper

# Townsville files the papers tabled at a meeting, and notes added after it,
# as events of their own beside the meeting: "Ordinary Council - Tabled
# Items", "Ordinary Council - Post Meeting Note", "Ordinary Council - Item 5
# - Post Event Report 2022". Each carries one packet of those papers and
# shares the meeting's type and date, so it would read as a second meeting
# whose agenda is a supplementary document. There are 37 of them, October
# 2020 to April 2023, and the meeting's own event is listed beside each
# one. Two of those—the Special Council meetings of 8 December 2020 and 1
# June 2021—are unpublished, so those meetings are left out rather than
# given their tabled papers as an agenda.
_SUPPLEMENTARY = re.compile(
    r"\b(tabled items?|post meeting note|post event report)\b", re.IGNORECASE
)


@register_scraper
class TownsvilleScraper(ResolveScraper):
    # Townsville's meetings page links the tenant's /web/ portal. The tenant
    # lists events back to 2008, but none before 2020 has a document, so its
    # record starts in 2020 and EARLIEST_YEAR bounds it already.
    tenant = "townsville"

    # Council (ordinary and special) and, until the standing committees
    # stopped meeting at the end of 2023 and Council went fortnightly, the
    # Planning and Development Committee. Left out are the other standing
    # committees of 2020-2023 (finance, infrastructure, water and waste,
    # community); each kept meeting costs a request to learn which
    # documents it has.
    meeting_types = re.compile(
        r"^(Ordinary Meeting|Special Meeting|Planning and Development Committee)$"
    )

    # Not `include_unpublished`: the events the API marks unpublished (in
    # range, mostly 2020—the Planning and Development Committee of July to
    # September, the Ordinary meeting of 30 June and four special meetings)
    # can only be checked through DocPreview, and townsville.resolve.red's
    # robots.txt is `Disallow: /`. The scraper requests only api.resolve.red
    # and emits the DocPreview links without fetching them.

    def __init__(self):
        super().__init__("townsville", "QLD")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        # Checked before the detail call, so a tabled-items event is free.
        if _SUPPLEMENTARY.search(event.get("name") or ""):
            return None
        return super()._record(event, today)
