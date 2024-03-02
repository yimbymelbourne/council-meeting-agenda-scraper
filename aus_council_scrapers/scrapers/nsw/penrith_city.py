from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class PenrithCityScraper(InfoCouncilScraper):
    def __init__(self):
        council = "penrith_city"
        state = "NSW"
        base_url = "https://www.penrithcity.nsw.gov.au/"
        infocouncil_url = "https://penrith.infocouncil.biz/"
        super().__init__(council, state, base_url, infocouncil_url)
