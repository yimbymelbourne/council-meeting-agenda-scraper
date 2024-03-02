from council_scrapers.base import InfoCouncilScraper, register_scraper

@register_scraper
class BurwoodNSWScraper(InfoCouncilScraper):
    def __init__(self):
        council = "burwood"
        state = "NSW"
        base_url = "https://burwood.nsw.gov.au"
        infocouncil_url = "https://burwood.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)


if __name__ == "__main__":
    scraper = BurwoodNSWScraper()
    scraper.scraper()
