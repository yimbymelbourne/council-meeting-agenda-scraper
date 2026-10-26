from aus_council_scrapers import clock
from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.burdekin.qld.gov.au"


@register_scraper
class BurdekinScraper(OpenCitiesContentScraper):
    # Two pages. The archive has an accordion per year from 2017, every
    # meeting but the latest; the Council meetings page has only the latest
    # meeting's papers, outside any accordion. Labels lead with an ISO date
    # ("2026-08-25 Ordinary Council Agenda"), typed loosely ("2025-08 26",
    # "22-04-12" for 2022-04-12). "Correspondence for Information" packets
    # sit beside each agenda and are not it.
    #
    # Burdekin also has a Resolve tenant, but it is patchy (nothing in
    # 2023–24) and stopped in April 2026; these pages are complete.
    pages = [
        ContentPage(
            f"{_BASE_URL}/About-council/Council-meetings/Archived-agendas-and-minutes"
        ),
        # The latest meeting is this year's, or last year's in January.
        ContentPage(
            f"{_BASE_URL}/About-council/Council-meetings",
            holds=lambda year: year >= clock.current_year() - 1,
        ),
    ]

    def __init__(self):
        super().__init__("burdekin", "QLD", _BASE_URL)
