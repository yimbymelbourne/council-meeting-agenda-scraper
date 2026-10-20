import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class KyogleScraper(ResolveScraper):
    # Kyogle's Resolve record starts with its 14 July 2025 Ordinary meeting.
    # The papers before that were on the council's old WordPress site, whose
    # listing pages 404 since the move to Drupal; the new site links only to
    # Resolve, so history before July 2025 is not online anywhere found.
    tenant = "kyogle"

    # Ordinary Council is the tenant's only meeting type; extraordinary
    # meetings are filed under it and named as such in the event. Naming it
    # keeps a committee the council starts publishing here from adding a
    # request per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^Ordinary Council$")

    def __init__(self):
        super().__init__("kyogle", "NSW")
