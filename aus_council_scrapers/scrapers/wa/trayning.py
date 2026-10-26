from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class TrayningScraper(SmallShireCouncilConnectScraper):
    """Shire of Trayning—documents on each meeting's own page.

    Council and electors' meetings; the audit committee ("Audit Comittee")
    and the LEMC are skipped by heading. The year listings carry no date, so
    every date comes from the meeting page, never the filename: the 18 June
    2025 meeting's papers are filed as "16 June 2025".

    Headings are hand-typed variations ("Ordinary Meeting of Council
    Meeting", "Special Ordinary Meeting of Council") and the electors' type
    is labelled just "Annual Electors", so each type gives the name.
    """

    type_names = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-meeting-of-council": "Special Meeting of Council",
        "annual-electors": "Annual Electors Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 27 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 27

    def __init__(self):
        super().__init__("trayning", "WA", "https://www.trayning.wa.gov.au")
