from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)


@register_scraper
class CoolgardieScraper(FilteredListingCouncilConnectScraper):
    """Shire of Coolgardie—documents on each meeting's own page.

    Council meetings only. A year is ~22 meetings, and the other five or so
    are the Audit, Risk and Improvement Committee (its type slug is spelt
    "commitee") and the annual electors' meeting; reading them would push a
    production year past 25 requests. The module starts in 2019.

    The upcoming page also carries a pasted block of this year's agendas and
    minutes as bare file links. The base reads only its meeting links, and
    those meetings come from the year listing anyway.

    The 26 March 2024 Ordinary agenda is emitted as the meeting page links
    it, though that link answered HTTP 500 twice on 20 Oct 2026 (its minutes
    are fine). The only other copy is under /Profiles/.../ModuleData/, which
    robots.txt disallows, so it is left for the council to fix.
    """

    # One production year: 15 requests, 27 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 27
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("coolgardie", "WA", "https://www.coolgardie.wa.gov.au")
