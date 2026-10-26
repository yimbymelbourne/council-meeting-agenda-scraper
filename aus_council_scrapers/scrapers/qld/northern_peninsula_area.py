import datetime

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.nparc.qld.gov.au"


@register_scraper
class NorthernPeninsulaAreaScraper(OpenCitiesContentScraper):
    # One page, an accordion per year back to 2009. NPARC titles its papers
    # by month ("January Council Meeting Agenda", "January Ordinary Council
    # Meeting Minutes - CONFIRMED"), calls most agendas a meeting "Booklet" or
    # "Book", and puts the day only in some filenames
    # ("...-27-january-2026-uploaded-on-website.pdf", "..._16012024___final").
    # The base takes the day from the filename ("24_november_ordinary_...",
    # "october_27th____meeting_papers"), or from the same meeting's other
    # paper that month, and otherwise from its papers' first page
    # (`pdf_dates`). A meeting none of these dates is left out (KNOWN_GAPS).
    #
    # The council also meets as trustee of the Deed of Grant in Trust land
    # it administers. Those Trustee meetings decide land matters and are on
    # the same page at no extra cost, so they are kept.
    agenda_words = (
        r"\bagendas?\b|\bbusiness\s+papers?\b|\bbooklets?\b|\bmeeting\s+book\b"
        r"|\bmeeting\s+papers\b"
    )
    pages = [ContentPage(f"{_BASE_URL}/Our-council/Council-meetings")]

    pdf_dates = True

    # Read once from the whole PDF, 26 Oct 2026, where `pdf_dates` cannot:
    # the March 2023 booklet's cover is past its first bytes and the file
    # is 9 MB ("Ordinary Council Meeting #35 ... Wednesday 22nd March
    # 2023"); three sets of minutes open with a page-long note of 21 April
    # 2023 and give the meeting's day on page 2 ("ORDINARY COUNCIL MEETING
    # #22 Wednesday, 16th February 2022"); and the "October" Trustee
    # meeting's agenda and minutes both say it was held on Friday 1st
    # November 2024. The month's other paper joins each.
    misfiled = {
        "may_20_ordinary_council_minutes-2023.pdf": datetime.date(2020, 5, 19),
        "spec_oct_2020_meeting_minutes.pdf": datetime.date(2020, 10, 2),
        "feb_22_ordinary_council_minutes-2023.pdf": datetime.date(2022, 2, 16),
        "march_council_meeting_book_for_publishing-2023.pdf": datetime.date(
            2023, 3, 22
        ),
        "october_trustee_meeting_book_publish-2024.pdf": datetime.date(2024, 11, 1),
        "trustee_01112024_final.pdf": datetime.date(2024, 11, 1),
    }

    def __init__(self):
        super().__init__("northern_peninsula_area", "QLD", _BASE_URL)
