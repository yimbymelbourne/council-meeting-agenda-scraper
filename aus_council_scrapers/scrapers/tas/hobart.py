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

    # Measured 19 Oct 2026 in one --years 2026 run with the other six
    # DocsPublished councils. They share DocAssembler's API, portal and blob
    # hosts, so they queue on one per-host spacing: 33 s, against 6 s run alone.
    expected_seconds = 33

    def __init__(self):
        super().__init__("hobart", "TAS")
