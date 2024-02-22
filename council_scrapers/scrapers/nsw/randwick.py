from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class RandwickScraper(InfoCouncilScraper):
    def __init__(self):
        council = "randwick"
        state = "NSW"
        base_url = "https://www.randwick.nsw.gov.au/"
        infocouncil_url = "https://randwick.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
