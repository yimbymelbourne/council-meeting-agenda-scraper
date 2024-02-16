from council_scrapers.base import InfoCouncilScraper
from council_scrapers.base import register_scraper


@register_scraper
class HornsbyScraper(InfoCouncilScraper):
    def __init__(self):
        council = "hornsby"
        state = "NSW"
        base_url = "https://www.hornsby.nsw.gov.au/"
        infocouncil_url = "https://businesspapers.hornsby.nsw.gov.au/"
        super().__init__(council, state, base_url, infocouncil_url)
