import datetime

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.murweh.qld.gov.au"


@register_scraper
class MurwehScraper(OpenCitiesContentScraper):
    # One page, an "Agendas" and a "Minutes" accordion per year from 2022.
    # Most labels are a sequence number and the meeting ("07 Council Meeting
    # 20 July 2023"), so the kind comes from the filename or, failing that,
    # the accordion. Papers are sometimes in the wrong accordion (a special
    # meeting's minutes under "2026 Agendas"), which is why a label that says
    # "Minutes" outranks the accordion it sits in.
    pages = [ContentPage(f"{_BASE_URL}/Council/About-Council/Agendas-and-Minutes")]

    misfiled = {
        # "08 General Meeting 22 July 2022", filed beside "08 Council Meeting
        # 21 July 2022" agenda, are that meeting's minutes. They read "HELD
        # ON THURSDAY 22 JULY 2022", but 22 July 2022 was a Friday; the
        # agenda reads "To be held Thursday 21 July 2022".
        "general_minutes_22_july_2022.pdf": datetime.date(2022, 7, 21),
    }

    def __init__(self):
        super().__init__("murweh", "QLD", _BASE_URL)
