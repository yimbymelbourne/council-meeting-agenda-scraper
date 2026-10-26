import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class WyndhamScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP in a full
    # 135-council run at 10 workers: 54 s, most of it queued behind the
    # other tenants on api.resolve.red (11 s alone). Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 54

    # Wyndham's own meetings page links out to its Resolve portal; the URL
    # docs/councils.md used to carry is an unpublished Drupal node that 403s
    # for everyone.
    tenant = "wyndham"

    # Council and Planning Committee. Wyndham re-created both types for the
    # 2024-2028 term ("Council Meeting 2024-2028"), and the old planning type
    # is spelt "Planning Commitee", hence the pattern. Left out is the
    # Contracts Approval Committee, which is procurement; each kept meeting
    # costs a request to learn which documents it has.
    meeting_types = re.compile(r"^(Council Meeting|Planning Committ?ee)")
    meeting_type_names = {"Planning Commitee": "Planning Committee"}

    def __init__(self):
        super().__init__("wyndham", "VIC")
