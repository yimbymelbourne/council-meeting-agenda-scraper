import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class HuntersHillScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP in a full
    # 135-council run at 10 workers: 32 s, most of it queued behind the
    # other tenants on api.resolve.red (6 s alone). Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 32

    # Hunters Hill left InfoCouncil for Resolve (#145); the old
    # huntershill.infocouncil.biz now 404s at every path.
    tenant = "huntershill"

    # Everything Hunters Hill has listed since 2020 is Ordinary Council
    # (extraordinary meetings included) or its Local Planning Panel. The
    # tenant also defines nine advisory committees that list nothing today;
    # naming the two keeps one that starts publishing from adding a request
    # per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^(Ordinary Council|Local Planning Panel)$")

    def __init__(self):
        super().__init__("hunters_hill", "NSW")
