from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WhitehorseScraper(InfoCouncilScraper):
    def __init__(self):
        council = "whitehorse"
        state = "VIC"
        base_url = "https://www.whitehorse.vic.gov.au/"
        infocouncil_url = "https://whitehorse.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_time = "7.00pm"
        self.default_location = (
            "Whitehorse Civic Centre, 379 Whitehorse Road, Nunawading"
        )
