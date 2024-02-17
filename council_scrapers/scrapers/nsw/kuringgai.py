from council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class KuRingGaiScraper(InfoCouncilScraper):
    def __init__(self):
        council = "kuringgai"
        state = "NSW"
        base_url = "http://eservices.kmc.nsw.gov.au/"
        infocouncil_url = "https://eservices.kmc.nsw.gov.au/Infocouncil.Web/"
        super().__init__(council, state, base_url, infocouncil_url)
