import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.burke.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Our-council/Council-Meetings"

# Every label leads with the meeting date as yymmdd: "260923 Agenda and
# Business Papers", "260916 Confirmed Minutes - Special Meeting".
_YYMMDD = re.compile(r"^\s*(\d{2})(\d{2})(\d{2})\b")


@register_scraper
class BurkeScraper(OpenCitiesContentScraper):
    # Two pages, agendas and minutes, each an accordion per year from 2017.
    # A label names its meeting only when it was not the ordinary monthly
    # one ("- Special Meeting", "- Post Election"); the rest are ordinary
    # meetings, as their PDFs are headed.
    pages = [
        ContentPage(f"{_MEETINGS}/Council-meeting-Agendas"),
        ContentPage(f"{_MEETINGS}/Council-Meeting-Minutes"),
    ]

    def __init__(self):
        super().__init__("burke", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # "200326 Agenda and Business Papers - Special meeting" (2020).
        label = re.sub(r"\bmeeting\b", "Meeting", label)
        # The base reads no undelimited six-digit date, so spell it out.
        m = _YYMMDD.match(label)
        if not m:
            return label
        yy, mm, dd = m.groups()
        rest = label[m.end() :]
        if not re.search(r"\bmeeting\b|\belection\b", rest, re.IGNORECASE):
            rest += " - Ordinary Meeting"
        return f"{int(dd)}/{int(mm)}/20{yy} {rest}"
