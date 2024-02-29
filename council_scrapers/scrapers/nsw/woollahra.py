from council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WoollahraScraper(InfoCouncilScraper):
    def __init__(self):
        council = "woollahra"
        state = "NSW"
        base_url = "https://www.woollahra.nsw.gov.au/"
        infocouncil_url = "https://woollahra.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
