import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class HinchinbrookScraper(ResolveScraper):
    # Hinchinbrook's Meetings-Minutes page links the tenant's /web/ portal,
    # which starts with the 23 January 2024 General Meeting. Earlier
    # meetings (2009 to 2023) are on
    # https://www.hinchinbrook.qld.gov.au/Our-Council/Meetings-Minutes/Archived-Minutes,
    # minutes only, which this scraper does not read yet, so its history
    # starts at the move.
    tenant = "hinchinbrook"
    resolve_from = datetime.date(2024, 1, 1)

    # The General Meeting is Council's ordinary meeting, with special
    # meetings filed under it ("Special Meeting - June 2024"); budget
    # meetings have a type of their own. These are the tenant's only two
    # types, named so that a committee the council starts publishing here
    # cannot add a request per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^(General Meeting|Budget Adoption)$")

    # "Budget Adoption" is the type; each of its events is a special meeting
    # ("Special Meeting - 23 June 2026") to adopt the budget.
    meeting_type_names = {"Budget Adoption": "Special Budget Meeting"}

    def __init__(self):
        super().__init__("hinchinbrook", "QLD")

    def _meeting_name(self, event: dict) -> str:
        # Before the Budget Adoption type existed, the 3 July 2024 budget
        # meeting was filed as a General Meeting ("Special Budget Meeting -
        # July 2024"), which the type alone would call a Special General
        # Meeting. Naming every budget meeting the same way lets a reader
        # find them all.
        if re.search(r"budget", event.get("name") or "", re.IGNORECASE):
            return "Special Budget Meeting"
        return super()._meeting_name(event)
