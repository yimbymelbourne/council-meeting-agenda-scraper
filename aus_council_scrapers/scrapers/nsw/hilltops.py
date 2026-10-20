import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class HilltopsScraper(ResolveScraper):
    # Hilltops moved to Resolve for its 22 October 2025 meeting; the tenant
    # holds nothing earlier. Meetings from 2016 to 24 September 2025 are on a
    # WordPress page (https://www.hilltops.nsw.gov.au/archived-agendas-and-minutes/)
    # that this scraper does not read: the page is about 76 MB, almost all of
    # it inline SVG icons.
    tenant = "hilltops"

    # Council meetings only. The Public Forum (also entered as "Open Forum")
    # sits half an hour before some Council meetings and decides nothing.
    meeting_types = re.compile(r"^(Ordinary Council|Extraordinary Council Meeting)$")

    # The council files extraordinary meetings under both types: 2 June 2026
    # under Ordinary Council, which the base class names "Extraordinary
    # Council", and 12 June 2026 under its own type. One name for both.
    meeting_type_names = {"Extraordinary Council Meeting": "Extraordinary Council"}

    def __init__(self):
        super().__init__("hilltops", "NSW")
