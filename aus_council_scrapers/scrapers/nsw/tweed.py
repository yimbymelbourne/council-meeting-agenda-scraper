import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class TweedScraper(ResolveScraper):
    # Tweed's Resolve record starts with its 6 February 2020 meetings. The
    # 2019-and-earlier papers are on the council website's archived-meetings
    # page, which this scraper does not read.
    #
    # The `pub-tweed` eScribe portal is Tweed, Ontario, not this council.
    tenant = "tweed"

    # The tenant has only these three types, so this keeps everything; it is
    # anchored so a committee added later does not quietly add a request per
    # meeting to the nightly run. "Ordinary Council PC" is the Council
    # meeting held straight after the Planning Committee on the first
    # Thursday of the month ("Starts at the conclusion of Planning
    # Committee"). Until mid-2021 the same meetings were typed plain
    # "Ordinary Council", so the two types are one body under two names.
    meeting_types = re.compile(
        r"^(Ordinary Council|Ordinary Council PC|Planning Committee)$"
    )
    meeting_type_names = {"Ordinary Council PC": "Ordinary Council"}

    # Not `include_unpublished`, although Tweed's /web/ portal does list the
    # 16 July 2020 Extraordinary meeting (the one past Council event the API
    # marks unpublished) with its agenda and minutes. Learning which of its
    # documents exist means asking DocPreview on tweed.resolve.red, and that
    # host's robots.txt is `Disallow: /`. So that meeting is left out.

    def __init__(self):
        super().__init__("tweed", "NSW")
