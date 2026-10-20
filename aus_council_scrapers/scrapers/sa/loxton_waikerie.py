"""District Council of Loxton Waikerie.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Council
meetings are on the agendas-and-minutes page, filed under "Agendas &
Minutes", which the base class reads as the council itself. The Riverland
Regional Assessment Panel, which decides development applications for
Loxton Waikerie, Berri Barmera and Renmark Paringa, is on a page of its own
and is read too. Each of the three councils republishes the panel's papers
in its own collection, so each of their scrapers carries the panel.

The many "Late Item" papers filed beside the agenda are excluded by the
base class, and the "Notice of Information Session" papers name no meeting
and are dropped with them.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper


@register_scraper
class LoxtonWaikerieScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.loxtonwaikerie.sa.gov.au/your-council/council-meetings/"
        "agendas-and-minutes",
        "https://www.loxtonwaikerie.sa.gov.au/your-council/"
        "committees-and-working-parties/riverland-regional-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__(
            "loxton_waikerie", "SA", "https://www.loxtonwaikerie.sa.gov.au"
        )
