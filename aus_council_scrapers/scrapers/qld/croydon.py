import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.croydon.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Your-Council/Council-Meetings"

# The meeting's number leads each label: "A0468 Agenda Ordinary Meeting 17
# September 2026", "AS467 Confirmed Minutes Special Meeting ...", typed
# with a letter O as often as a zero ("AO417").
_MEETING_NUMBER = re.compile(r"^\s*A[SO0]?\d{2,4}[\s_]+", re.IGNORECASE)


@register_scraper
class CroydonScraper(OpenCitiesContentScraper):
    # Two pages, agendas and minutes, every year from 2016 on each: the
    # latest years loose at the top, older ones in an accordion per year.
    # The "Previous-Years" pages the menu also links repeat 2016–2023.
    # A "Notice of Special Meeting" sits beside most special agendas and
    # is not one.
    pages = [
        ContentPage(f"{_MEETINGS}/Council-Agendas"),
        ContentPage(f"{_MEETINGS}/Council-Minutes"),
    ]

    def __init__(self):
        super().__init__("croydon", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # The number would otherwise become part of the meeting's name.
        # Some labels are the filename ("AO407_Confirmed_Minutes_..."), whose
        # underscores hide the words from the base.
        label = _MEETING_NUMBER.sub("", label.replace("_", " "))
        # One spelling per meeting type: "Ordinary meeting" (16 March 2023)
        # beside "Ordinary Meeting", "Post-Election" beside "Post Election".
        label = re.sub(r"\bmeeting\b", "Meeting", label)
        return re.sub(r"\bPost-Election\b", "Post Election", label, flags=re.IGNORECASE)
