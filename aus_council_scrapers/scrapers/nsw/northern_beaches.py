from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class NorthernBeachesScraper(DocsPublishedScraper):
    # Northern Beaches left InfoCouncil — northernbeaches.infocouncil.biz now
    # 404s at every path — for DocAssembler.
    publishing_slug = "northernbeaches"

    def __init__(self):
        super().__init__("northern_beaches", "NSW")
        self.default_location = "Civic Centre, 7 Civic Drive, Dee Why"
