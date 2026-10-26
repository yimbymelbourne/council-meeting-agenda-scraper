import datetime

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
    # have none ("march_agenda.pdf") and are dated from their papers' first
    # page (`pdf_dates`). A meeting neither paper dates is left out rather
    # than given an invented day, each logged; conformance.KNOWN_GAPS
    # records what is left.
    #
    # The August and December 2022 minutes links are one file, the 16 August
    # minutes, so December 2022 has its agenda only.
    pages = [ContentPage(f"{_BASE_URL}/Your-Council/Council-Meetings-and-Agendas")]

    pdf_dates = True

    # Covers past the first bytes of a 22-37 MB file, read once from the
    # whole PDF, 26 Oct 2026: "AGENDA - SPECIAL COUNCIL MEETING 03 NOVEMBER
    # 2021" (its minutes say the same), and "MINUTES 28 OCTOBER 2020".
    misfiled = {
        "council_meeting___special_meeting___november_2021___agenda.pdf": (
            datetime.date(2021, 11, 3)
        ),
        "council_meeting___special_meeting___november_2021___minutes.pdf": (
            datetime.date(2021, 11, 3)
        ),
        "council_meeting___october_2020___minutes_with_appendices.pdf": (
            datetime.date(2020, 10, 28)
        ),
    }

    def __init__(self):
        super().__init__("flinders_qld", "QLD", _BASE_URL)
