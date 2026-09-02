from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class MosmanScraper(DocsPublishedScraper):
    publishing_slug = "mosmancouncil"
    org_id = "2a4f66d6-9e85-4b77-84c7-271910bff13d"

    def __init__(self):
        super().__init__("mosman", "NSW")
