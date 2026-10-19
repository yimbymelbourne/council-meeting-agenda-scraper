from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class CottesloeScraper(CouncilConnectScraper):
    """Town of Cottesloe—documents on each meeting's own page.

    Every meeting type is read: there are only three (Ordinary, Special,
    Electors), and a year runs to about 15 meetings, so one production year
    costs ~17 requests—two listing pages, the meeting pages, the upcoming
    page and whichever upcoming meeting is close enough to have an agenda.
    """

    def __init__(self):
        super().__init__("cottesloe", "WA", "https://www.cottesloe.wa.gov.au")
