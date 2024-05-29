from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WaverleyScraper(InfoCouncilScraper):
    def __init__(self):
        council = "waverley"
        state = "NSW"
        base_url = "https://www.waverley.nsw.gov.au/"
        infocouncil_url = "https://waverley.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_location = "Cnr Paul Street and Bondi Road, Bondi Junction"
        self.default_time = "7 PM"
