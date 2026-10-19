from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class WyalkatchemScraper(SmallShireCouncilConnectScraper):
    """Shire of Wyalkatchem—documents on each meeting's own page.

    Ordinary meetings are filed under two types, "Ordinary" and "Ordinary
    Council Meetings", in alternate months, and Special meetings under
    "Special". Those labels are too bare to name a meeting ("Ordinary"), so
    `type_names` gives each its full name. The audit committee and the LEMC
    are skipped by heading. Special meetings are frequent here (seven in
    2025), so a production year runs to about 20–24 requests.

    Meetings before 2025 have no documents block: their PDFs are linked from
    the meeting description under /Assets/ClientData/, which the shared
    class reads when the block is missing.
    """

    type_names = {
        "ordinary": "Ordinary Council Meeting",
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special": "Special Council Meeting",
        "electors": "Annual Electors Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 38 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 38

    def __init__(self):
        super().__init__("wyalkatchem", "WA", "https://www.wyalkatchem.wa.gov.au")
