import datetime
import re

from bs4 import Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.grc.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"


@register_scraper
class GoondiwindiScraper(OpenCitiesContentScraper):
    # This year's agendas and minutes each have a page; earlier agendas
    # (2023–2025) are on Previous-Agendas, one accordion a year. Nothing
    # older than 2023 has an agenda online.
    #
    # Earlier minutes have a page a year, and the pages have moved as they
    # aged: 2025's is under Minutes ("Minutes/2025-Minutes"), 2020–2024's
    # under Previous-Meeting-Minutes ("Previous-Meeting-Minutes/2021-
    # Minutes"). No page or menu links them—Previous-Meeting-Minutes itself
    # holds only 2010–2019 in accordions—so they are found from the
    # sitemap, which lists every one. That costs one request a night and
    # finds this year's page wherever the council moves it next January.
    #
    # An ordinary meeting's agenda is titled by its sequence number and date
    # alone ("9. 23 September 2026"); only other meetings are named
    # ("6. 17 June 2026 - Special Meeting").
    year_index = f"{_BASE_URL}/sitemap.xml"
    year_page = re.compile(
        r"/Council/Council-Meetings/(?:Previous-Meeting-)?Minutes/(?P<year>\d{4})-Minutes$"
    )
    pages = [
        # This year's, and in January still last year's December papers.
        ContentPage(
            f"{_MEETINGS}/Agendas", holds=lambda y: y >= clock.current_year() - 1
        ),
        ContentPage(
            f"{_MEETINGS}/Minutes", holds=lambda y: y >= clock.current_year() - 1
        ),
        ContentPage(
            f"{_MEETINGS}/Previous-Agendas", holds=lambda y: y < clock.current_year()
        ),
    ]

    misfiled = {
        # Labelled "01. Confirmed Minutes - Ordinary Meeting - 27 January 20",
        # on the 2021 page; the PDF reads "Wednesday, 27 January 2021".
        "01._confirmed_minutes___ordinary_meeting___27_january_2021.pdf": datetime.date(
            2021, 1, 27
        ),
        # Labelled and named 23 April 2024, a Tuesday, beside the 24 April
        # agenda; the PDF reads "Wednesday, 24 April 2024".
        "5._confirmed_minutes___ordinary_meeting___23_april_2024.pdf": datetime.date(
            2024, 4, 24
        ),
        # Labelled and named 22 June 2022; the PDF reads "Monday, 20 June
        # 2022", opened at 11.00am after that morning's ordinary meeting.
        "06._confirmed_minutes___special_budget_meeting___22_june_2022.pdf": (
            datetime.date(2022, 6, 20)
        ),
    }

    def __init__(self):
        super().__init__("goondiwindi", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # "Website Agenda 13 December 2023": the copy for the website.
        label = re.sub(r"^\s*website\s+", "", label, flags=re.IGNORECASE)
        # "Post-Election Meeting" (2024 agenda) is the "Post Election
        # Meeting" of the minutes.
        label = re.sub(r"\bPost-Election\b", "Post Election", label, flags=re.IGNORECASE)
        # The base takes no kind from the accordion for a label that names
        # no meeting, so name the ordinary meeting such a label stands for.
        if not re.search(r"\bmeeting\b", label, re.IGNORECASE):
            label += " - Ordinary Meeting"
        return label
