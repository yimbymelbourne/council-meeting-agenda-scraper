from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class GeorgesRiverScraper(InfoCouncilScraper):
    def __init__(self):
        council = "georges_river"
        state = "NSW"
        base_url = "https://www.georgesriver.nsw.gov.au/"
        infocouncil_url = "https://georgesriver.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
        self.default_time = "6:00pm"
        self.default_location = "Dragon Room, Level 1, Georges River Civic Centre Corner Dora and MacMahon Streets, Hurstville"


if __name__ == "__main__":
    scraper = GeorgesRiverScraper()
    scraper.scraper()
