from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class VictoriaParkScraper(CouncilConnectScraper):
    """Town of Victoria Park—documents on each meeting's own page.

    Council meetings only. The town lists more than 50 meetings a year—
    Agenda Briefing Forums and a dozen advisory and working groups—and each
    costs a request, ~60 a production year. Ordinary and Special Council
    meetings alone, through their own year pages, are ~20.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("victoria_park", "WA", "https://www.victoriapark.wa.gov.au")
