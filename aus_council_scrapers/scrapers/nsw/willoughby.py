import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class WilloughbyScraper(ResolveScraper):
    # Willoughby moved to Resolve around October 2024; the tenant's earliest
    # event is 21 October 2024. Meetings from 2015 to August 2024 are on an
    # OpenCities archive page that this scraper does not read, so its history
    # starts at the move.
    tenant = "willoughby"

    # Council meetings only—"Council Meeting" for this term, "2021 - 2024
    # Council Meeting" for the last. The tenant's other busy type is the
    # Public and Open Forum held before each Council meeting, where residents
    # address councillors and nothing is decided; the rest are advisory
    # committees and audit. Each kept meeting costs a request to learn which
    # documents it has.
    meeting_types = re.compile(r"Council Meeting$")

    def __init__(self):
        super().__init__("willoughby", "NSW")
