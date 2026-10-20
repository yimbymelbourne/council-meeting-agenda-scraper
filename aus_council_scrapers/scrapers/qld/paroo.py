from aus_council_scrapers import clock
from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.paroo.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Publications/Council-Meetings"


@register_scraper
class ParooScraper(OpenCitiesContentScraper):
    # Two pages: this year's meetings, and an accordion per earlier year back
    # to 2016. Workshop agendas and special meeting notices are filed among
    # the papers and are dropped by the base. The 15 March 2022 minutes are
    # linked as "General Meeting Agenda (Supplementary)"; the base reads them
    # as minutes from the filename. Paroo's own name for an
    # ordinary meeting changed from "General Meeting" to "Ordinary Council
    # Meeting" in 2024, sometimes with one name on the agenda and the other
    # on the minutes; the base treats them as one.
    pages = [
        ContentPage(
            f"{_MEETINGS}/Current-Year-Meetings",
            # In January last year's papers may not have moved yet.
            holds=lambda year: year >= clock.current_year() - 1,
        ),
        ContentPage(
            f"{_MEETINGS}/Previous-Years-Meetings",
            holds=lambda year: year < clock.current_year(),
        ),
    ]

    def __init__(self):
        super().__init__("paroo", "QLD", _BASE_URL)
