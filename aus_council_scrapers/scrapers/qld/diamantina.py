from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.diamantina.qld.gov.au"


@register_scraper
class DiamantinaScraper(OpenCitiesContentScraper):
    # One page, an accordion per year: agendas and minutes from 2020, minutes
    # only before that. Labels are "Public Agenda: Ordinary Council Meeting -
    # 12 October 2026" or, until 2024, "Minutes - Ordinary Council Meeting
    # December 18, 2024". "Late Agenda" and "Agenda Item 8 Reports" papers sit
    # beside each public agenda and are not it; where a meeting has both
    # "Confirmed Minutes" and "Confirmed Amended Minutes", the amended set is
    # the one that stands.
    pages = [
        ContentPage(
            f"{_BASE_URL}/Council/Council-Meetings/Meetings-Agendas-and-Minutes"
        )
    ]

    def __init__(self):
        super().__init__("diamantina", "QLD", _BASE_URL)
