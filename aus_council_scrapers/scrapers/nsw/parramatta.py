from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class ParramattaScraper(DocsPublishedScraper):
    # One production year, measured Oct 2026 from a home IP: 17 s. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 17

    publishing_slug = "CityofParramatta"

    def __init__(self):
        super().__init__("parramatta", "NSW")
