import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class WalgettScraper(ResolveScraper):
    # Walgett's tenant holds ten 2016 meetings and then its continuous
    # record from 22 October 2024. Nothing from 2017 to September 2024 is on
    # Resolve, and the council's own site is a JavaScript app with no
    # meetings archive found, so history in range starts in October 2024.
    tenant = "walgett"

    # "Ordinary Council Meeting" is the tenant's only type; extraordinary
    # meetings are filed under it and named as such in the event. Naming it
    # keeps a committee the council starts publishing here from adding a
    # request per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^Ordinary Council Meeting$")

    def __init__(self):
        super().__init__("walgett", "NSW")

    def _meeting_name(self, event: dict) -> str:
        # The 10 March 2026 meeting is "Extra Ordinary Meeting", which the
        # base class's special-meeting match reads as two words and so as an
        # Ordinary meeting.
        name = _EXTRA_ORDINARY.sub("Extraordinary", event.get("name") or "")
        return super()._meeting_name({**event, "name": name})


_EXTRA_ORDINARY = re.compile(r"\bextra[\s-]+ordinary\b", re.IGNORECASE)
