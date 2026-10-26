from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class CueScraper(SmallShireCouncilConnectScraper):
    """Shire of Cue—documents on each meeting's own page.

    Council and electors' meetings; the audit committee is skipped by
    heading. The 21 April 2026 meeting is filed under a one-off type named
    after it, which is why the all-types listing is read rather than a list
    of types.

    Cue also has a Resolve portal (`cue.resolve.red`), but no event on it
    has a published agenda or minutes, so it is not read.
    """

    # One production year, measured 20 Oct 2026 from a home IP: 30 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 30

    def __init__(self):
        super().__init__("cue", "WA", "https://www.cue.wa.gov.au")
