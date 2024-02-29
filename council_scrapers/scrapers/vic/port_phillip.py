from council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class PortPhilipScraper(InfoCouncilScraper):
    def __init__(self):
        council = "port_philip"
        state = "VIC"
        base_url = "https://www.portphillip.vic.gov.au/"
        infocouncil_url = "https://portphillip.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
