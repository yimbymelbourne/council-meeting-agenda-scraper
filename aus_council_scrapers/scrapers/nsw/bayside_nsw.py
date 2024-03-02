from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class BaysideNSWScraper(InfoCouncilScraper):
    def __init__(self):
        council = "bayside"
        state = "NSW"
        base_url = "https://bayside.nsw.gov.au"
        infocouncil_url = "https://infoweb.bayside.nsw.gov.au/?committee=1"
        super().__init__(council, state, base_url, infocouncil_url)
