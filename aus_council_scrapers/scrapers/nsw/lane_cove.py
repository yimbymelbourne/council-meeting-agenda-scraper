from aus_council_scrapers.base import InfoCouncilScraper
from aus_council_scrapers.base import register_scraper


@register_scraper
class LaneCoveScraper(InfoCouncilScraper):
    def __init__(self):
        council = "lane_cove"
        state = "NSW"
        base_url = "https://lanecove.infocouncil.biz"
        infocouncil_url = "https://lanecove.infocouncil.biz"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_location = (
            "Lane Cove Council Civic Centre at 48 Longueville Road, Lane Cove"
        )
