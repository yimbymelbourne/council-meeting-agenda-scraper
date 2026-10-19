from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.flinders.qld.gov.au"


@register_scraper
class FlindersQldScraper(OpenCitiesContentScraper):
    # One page, an "Agenda and Minutes" accordion per year from 2020, labels
    # like "01. Ordinary Council Meeting - 28 January 2026 - Agenda".
    #
    # From 2020 to 2023 most ordinary meetings are labelled by month only
    # ("Council Meeting - March 2023 - Agenda"). Where the filename has the
    # day ("agenda_with_appendices-11-oct.pdf"), the base takes it; most
    # have none ("march_agenda.pdf") and are left out rather than given an
    # invented day, each logged. conformance.KNOWN_GAPS records the gap.
    #
    # The August and December 2022 minutes links are one file, the 16 August
    # minutes, so December 2022 has its agenda only.
    pages = [ContentPage(f"{_BASE_URL}/Your-Council/Council-Meetings-and-Agendas")]

    def __init__(self):
        super().__init__("flinders_qld", "QLD", _BASE_URL)
