from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class InnerWestScraper(InfoCouncilScraper):
    def __init__(self):
        council = "inner_west"
        state = "NSW"
        base_url = "https://innerwest.infocouncil.biz"
        infocouncil_url = "https://innerwest.infocouncil.biz/Default.aspx"
        super().__init__(council, state, base_url, infocouncil_url)
