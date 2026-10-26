import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BananaScraper(ResolveScraper):
    # Banana Shire moved to Resolve for 2026: its "2026 Council Agendas and
    # Meeting Minutes" page frames the portal, and the tenant holds 2026
    # alone. Earlier years are on the council's OpenCities pages (confirmed
    # minutes from 2016, agendas only from August 2025) and are not read
    # here yet, so `resolve_from` keeps those years from costing listing
    # calls and the output starts in 2026.
    tenant = "banana"
    resolve_from = datetime.date(2026, 1, 1)

    # The tenant's two types ("Special Council " carries a trailing space,
    # which the base class strips). Naming them keeps a committee the
    # council starts publishing here from adding a request per meeting
    # unasked.
    meeting_types = re.compile(r"^(Ordinary|Special) Council$")

    # The council's papers say "Ordinary Council Meeting" (the 23 September
    # 2026 agenda's cover), as Richmond's and Napranum's names do.
    meeting_type_names = {
        "Ordinary Council": "Ordinary Council Meeting",
        "Special Council": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("banana", "QLD")
