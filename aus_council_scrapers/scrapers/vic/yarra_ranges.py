from aus_council_scrapers.base import DocsPublishedScraper, register_scraper


@register_scraper
class YarraRangesScraper(DocsPublishedScraper):
    # White-labelled: the app is also served from the council's own domain, but
    # only docspublished.com.au resolves /document/<id>, so keep the canonical
    # host. The council page in docs/councils.md is a landing page that links to
    # it, which is why the platform sweep missed this one.
    publishing_slug = "yarraranges"

    def __init__(self):
        super().__init__("yarra_ranges", "VIC")
