import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class GunnedahScraper(ResolveScraper):
    # The council's Agendas, Minutes & Recordings page frames the tenant's
    # older /web/ portal (Gunnedah.civicclerk.com.au, the same tenant).
    tenant = "gunnedah"

    # Council meetings, extraordinary ones included, and the Planning,
    # Environment and Development Committee, which takes the development
    # applications. The only other type is the Public Forum (from April
    # 2026), which decides nothing.
    meeting_types = re.compile(
        r"^(Ordinary Council|Extraordinary Council"
        r"|Planning Environment And Development Committee)$"
    )

    # Every event from 2016 to March 2023 is marked unpublished in the API.
    # The /web/ portal's search still lists them, and DocPreview still
    # serves their business papers and minutes, so `include_unpublished`
    # would recover about 60 meetings from 2020 to March 2023. It is left
    # off because finding out which documents an unpublished event has means
    # asking DocPreview on gunnedah.resolve.red, and that host's robots.txt
    # is "Disallow: /" (so is Gunnedah.civicclerk.com.au's). Published
    # events cost only api.resolve.red calls, which have no robots.txt.
    # The record therefore starts in 2023 unless the project decides that
    # probing DocPreview is acceptable (Woollahra already does it).

    def __init__(self):
        super().__init__("gunnedah", "NSW")
