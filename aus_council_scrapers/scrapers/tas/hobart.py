from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class HobartScraper(DocsPublishedScraper):
    # Linked as "agendas and minutes" from hobartcity.com.au, which is
    # OpenCities; the documents themselves are all on docspublished, from
    # January 2016 (older ones are by request to Governance). Committees are
    # included—City Planning and the Planning Authority Committee are where
    # development applications are decided. Meeting types carry "Open
    # Portion" because the closed portion is never published.
    publishing_slug = "hobartcity"

    def __init__(self):
        super().__init__("hobart", "TAS")
