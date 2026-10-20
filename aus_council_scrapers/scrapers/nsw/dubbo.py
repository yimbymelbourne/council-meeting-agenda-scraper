import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class DubboScraper(ResolveScraper):
    # Dubbo moved to Resolve in November 2025; the tenant's first event is
    # the 11 November 2025 Standing Committees meeting. Older papers are
    # .PDF.aspx files on the council's Kentico site, which this scraper does
    # not read.
    tenant = "dubbo"

    # Council, and the monthly Standing Committees meeting. That one event
    # holds three committees in turn, and the first of them, Infrastructure,
    # Planning and Environment, determines development applications. The
    # only type left out is the Public Forum before Council meetings, where
    # residents address councillors and nothing is decided.
    meeting_types = re.compile(r"^(Ordinary Council|Standing Committees)$")

    def __init__(self):
        super().__init__("dubbo", "NSW")
