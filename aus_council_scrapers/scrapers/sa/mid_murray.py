"""Mid Murray Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. There is no
page over the whole collection: council meetings and the Council Assessment
Panel each have one, and their labels ("Council Meeting Agendas & Minutes",
"Council Assessment Panel Agenda and Minutes") lose the page suffix in the
base class. Most months the panel files only a "Notice of Cancelled
Meeting", which the base class excludes.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper


@register_scraper
class MidMurrayScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.mid-murray.sa.gov.au/council/council-agendas-and-minutes/"
        "council-agendas-and-minutes",
        "https://www.mid-murray.sa.gov.au/council/council-assessment-panel/"
        "council-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("mid_murray", "SA", "https://www.mid-murray.sa.gov.au")
