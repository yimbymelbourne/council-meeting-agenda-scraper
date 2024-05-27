from aus_council_scrapers.base import InfoCouncilScraper
from aus_council_scrapers.base import register_scraper


@register_scraper
class HuntersHillScraper(InfoCouncilScraper):
    def __init__(self):
        council = "hunters_hill"
        state = "NSW"
        base_url = "https://www.huntershill.nsw.gov.au/"
        infocouncil_url = "https://huntershill.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_location = "Town Hall, 22 Alexandra Street, Hunters Hill NSW 2110"
        self.default_time = "6pm"
