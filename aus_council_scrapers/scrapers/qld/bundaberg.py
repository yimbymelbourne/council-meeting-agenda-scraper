import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BundabergScraper(ResolveScraper):
    # Bundaberg's Council-meetings page links the tenant's /web/ portal.
    # Bundaberg moved to Resolve for its 23 August 2022 Ordinary meeting.
    # Earlier papers (2016 to July 2022) are direct PDF links in per-year
    # accordions on https://www.bundaberg.qld.gov.au/Council/Council-meetings,
    # which this scraper does not read yet, so its history starts at the move.
    tenant = "bundaberg"
    resolve_from = datetime.date(2022, 8, 23)

    # Every event is this type, special and budget meetings included
    # ("Special Meeting of Council 9 April 2024", "Special Budget Meeting"),
    # and the base class names those from the event name. Naming it keeps a
    # committee the council starts publishing here from adding a request
    # per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^Ordinary Council Meeting$")

    # Not `include_unpublished`: the budget meetings (28 June 2024, 30 June
    # 2025, and 2 June 2026 with its continuation on 9 June) and the special
    # meeting of 8 May 2024 are marked unpublished, and checking them would
    # mean asking DocPreview, which bundaberg.resolve.red's robots.txt
    # (`Disallow: /`) rules out. The scraper requests only api.resolve.red
    # and emits the DocPreview links without fetching them.

    def __init__(self):
        super().__init__("bundaberg", "QLD")
