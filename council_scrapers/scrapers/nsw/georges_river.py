from council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class GeorgesRiverScraper(InfoCouncilScraper):
    def __init__(self):
        council = "georges_river"
        state = "NSW"
        base_url = "https://www.georgesriver.nsw.gov.au/"
        infocouncil_url = "https://georgesriver.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = GeorgesRiverScraper()
    scraper.scraper()
