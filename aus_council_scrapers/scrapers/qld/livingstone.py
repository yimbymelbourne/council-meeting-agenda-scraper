from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.livingstone.qld.gov.au"


@register_scraper
class LivingstoneScraper(OpenCitiesContentScraper):
    # One page, 2018 to now, an "Agendas" and a "Minutes" accordion per year.
    # Both hold far more than the two papers: officer and deputation
    # presentations, late agendas and attachment books, all titled like the
    # papers ("Ordinary Council Meeting - Officer Presentation - Item 13.1 -
    # ... - 6 October 2026"), which the base's exclusions drop. Agendas often
    # come in parts, and part one is kept. The committees of 2024–25
    # (Development and Environment, Infrastructure, Recreation and Culture)
    # and the Blueprint Livingstone Committee are on the same page and cost
    # nothing extra, so they are kept too.
    pages = [
        ContentPage(
            f"{_BASE_URL}/Your-Council/About-Council/Council-Meetings-and-Agendas"
        )
    ]

    def __init__(self):
        super().__init__("livingstone", "QLD", _BASE_URL)
