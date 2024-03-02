from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class NorthernBeachesScraper(InfoCouncilScraper):
    def __init__(self):
        council = "northern_beaches"
        state = "NSW"
        base_url = "https://www.northernbeaches.nsw.gov.au/"
        infocouncil_url = "https://northernbeaches.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
