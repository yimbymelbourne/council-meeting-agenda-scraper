from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class ParramattaScraper(DocsPublishedScraper):
    publishing_slug = "CityofParramatta"

    def __init__(self):
        super().__init__("parramatta", "NSW")
