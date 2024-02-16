from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class ParramattaScraper(InfoCouncilScraper):
    def __init__(self):
        council = "parramatta"
        state = "NSW"
        base_url = "https://businesspapers.parracity.nsw.gov.au"
        infocouncil_url = "https://businesspapers.parracity.nsw.gov.au"
        super().__init__(council, state, base_url, infocouncil_url)
