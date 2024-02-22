from council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WhitehorseScraper(InfoCouncilScraper):
    def __init__(self):
        council = "whitehorse"
        state = "VIC"
        base_url = "https://www.whitehorse.vic.gov.au/"
        infocouncil_url = "https://whitehorse.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
