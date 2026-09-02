from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class ParramattaScraper(DocsPublishedScraper):
    publishing_slug = "CityofParramatta"
    org_id = "06b8d045-4f33-426f-bf4a-300486492563"

    def __init__(self):
        super().__init__("parramatta", "NSW")
