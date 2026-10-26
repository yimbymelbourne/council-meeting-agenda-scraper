import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import OpenCitiesContentScraper

_BASE_URL = "https://www.bulloo.qld.gov.au"
_INDEX = f"{_BASE_URL}/About-Council/Meeting-Agenda-Minutes"


@register_scraper
class BullooScraper(OpenCitiesContentScraper):
    # A page per year from 2021 (nothing older is online), each with a
    # "Council Meeting Agenda" and a "Council Meeting Minutes" accordion.
    # 2021 and 2022 labels are mostly only the date ("25 January 2022",
    # "19 July 2022 (Special)"), so the accordion gives the kind. Late items are
    # listed beside their agenda and are not it. An ordinary and a special
    # meeting on one day (16 July 2026) stay two meetings because each
    # label names its own.
    year_index = _INDEX
    year_page = re.compile(r"/Meeting-Agenda-Minutes/Council-Meetings-(?P<year>\d{4})$")

    def __init__(self):
        super().__init__("bulloo", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # "Counicl" (August 2026, December 2025 minutes) would otherwise be a
        # body of its own and split the meeting from its agenda.
        label = re.sub(r"\bcounicl\b", "Council", label, flags=re.IGNORECASE)
        # A label that is only a date names no meeting, and the base takes
        # no kind from the accordion for it. These are Council meetings:
        # ordinary unless the label says special.
        # "Council Meeting 18 July 2023 (Special)" is a special meeting.
        if re.search(r"\bmeeting\b.*\(special\)", label, re.IGNORECASE):
            label = "Special " + re.sub(
                r"\s*\(special\)", "", label, flags=re.IGNORECASE
            )
        if not re.search(r"\bmeeting\b|\bagenda\b|\bminutes\b", label, re.IGNORECASE):
            kind = (
                "Special"
                if re.search(r"\bspecial\b", label, re.IGNORECASE)
                else "Ordinary"
            )
            label = re.sub(r"[\s(-]*\bspecial\b\)?", "", label, flags=re.IGNORECASE)
            label = f"{label} - {kind} Council Meeting"
        return label
