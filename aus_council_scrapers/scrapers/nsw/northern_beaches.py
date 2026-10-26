from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class NorthernBeachesScraper(DocsPublishedScraper):
    # One production year, measured 19 Oct 2026 from a home IP in a full
    # 135-council run at 10 workers: 21 s, queued with the other six
    # DocsPublished councils on DocAssembler's shared hosts (16 s at 6
    # workers). Orders dispatch only; see BaseScraper.expected_seconds.
    expected_seconds = 21

    # Northern Beaches left InfoCouncil — northernbeaches.infocouncil.biz now
    # 404s at every path — for DocAssembler.
    publishing_slug = "northernbeaches"

    def __init__(self):
        super().__init__("northern_beaches", "NSW")
        self.default_location = "Civic Centre, 7 Civic Drive, Dee Why"
