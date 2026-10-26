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
    # paper that month; a meeting with no day anywhere is left out, which is
    # most of 2021 and many special and Trustee meetings (KNOWN_GAPS).
    #
    # The council also meets as trustee of the Deed of Grant in Trust land
    # it administers. Those Trustee meetings decide land matters and are on
    # the same page at no extra cost, so they are kept.
    agenda_words = (
        r"\bagendas?\b|\bbusiness\s+papers?\b|\bbooklets?\b|\bmeeting\s+book\b"
        r"|\bmeeting\s+papers\b"
    )
    pages = [ContentPage(f"{_BASE_URL}/Our-council/Council-meetings")]

    def __init__(self):
        super().__init__("northern_peninsula_area", "QLD", _BASE_URL)
