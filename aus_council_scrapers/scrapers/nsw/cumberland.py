from council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class CumberlandScraper(InfoCouncilScraper):
    def __init__(self):
        council = "cumberland"
        state = "NSW"
        base_url = "https://www.cumberland.nsw.gov.au/"
        infocouncil_url = "https://cumberland.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
