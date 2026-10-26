from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class MosmanScraper(DocsPublishedScraper):
    publishing_slug = "mosmancouncil"

    def __init__(self):
        super().__init__("mosman", "NSW")
