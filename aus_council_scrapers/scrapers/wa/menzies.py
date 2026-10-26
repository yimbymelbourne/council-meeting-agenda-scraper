from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class MenziesScraper(SmallShireCouncilConnectScraper):
    """Shire of Menzies—documents on each meeting's own page.

    Council and electors' meetings. The audit committee and, in 2026, five
    CEO Selection Committee meetings are skipped by heading, which keeps
    2026 near 16 requests instead of 24.
    """

    # One production year, measured 20 Oct 2026 from a home IP: 34 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 34

    def __init__(self):
        super().__init__("menzies", "WA", "https://www.menzies.wa.gov.au")
