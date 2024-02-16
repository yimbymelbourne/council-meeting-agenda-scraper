from council_scrapers.base import InfoCouncilScraper
from council_scrapers.base import register_scraper


@register_scraper
class LiverpoolScraper(InfoCouncilScraper):
    def __init__(self):
        council = "liverpool"
        state = "NSW"
        base_url = "https://www.liverpool.nsw.gov.au/"
        infocouncil_url = "https://liverpool.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
