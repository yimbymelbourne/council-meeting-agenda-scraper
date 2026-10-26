from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)


@register_scraper
class PlantagenetScraper(WATidyCouncilConnectScraper):
    """Shire of Plantagenet—documents on each meeting's own page.

    Council meetings only. Most years the other types are the audit
    committee and the electors' meeting, but 2023 also had the saleyards,
    roadwise, emergency management, CEO appointment and heavy plant
    committees, 19 meetings beyond the Council's 15, each a request.

    The upcoming page lists no meetings: the Shire enters a meeting in the
    module only once it has been held, so an agenda is first visible here
    the day after the meeting it is for.

    The site is behind Cloudflare (`server: cloudflare`, a `cf-ray` on every
    response), with no challenge seen from a home connection on 20 Oct 2026
    and not yet measured from a GitHub runner.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 29 s for
    # 15 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 29

    def __init__(self):
        super().__init__("plantagenet", "WA", "https://www.plantagenet.wa.gov.au")
