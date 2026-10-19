import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.southburnett.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Your-Council/About-Council/Council-Meetings"

_KIND = re.compile(r"\bagendas?\b|\bminutes\b", re.IGNORECASE)
_MEETING = re.compile(r"\bmeeting\b", re.IGNORECASE)
_TIME = re.compile(r"\b\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\b", re.IGNORECASE)

# Links a row files under the wrong meeting, by filename and the meeting the
# row names. The 19 May 2021 Executive and Finance & Corporate Standing
# Committee row links the Budget Committee's minutes of that day, which the
# Budget Committee's own row links too; that committee's minutes are not
# online.
_WRONG_ROW = {
    (
        "minutes___budget_committee_meeting___19_may_2021.pdf",
        "Executive and Finance & Corporate Standing Committee",
    ),
}
# Links a row files under the wrong meeting, with the meeting they are for.
# The 15 July 2020 row is the budget meeting and the general meeting after
# it; its plain "Minutes" are the general meeting's (the budget meeting's
# are "Budget Minutes").
_ROW_MEETING = {"minutes___15_july_2020.pdf": "General Meeting"}


@register_scraper
class SouthBurnettScraper(OpenCitiesContentScraper):
    # Two pages of tables, a row per meeting: this year's on the Council
    # Meetings page, and every earlier year back to 2012 on Previous Council
    # Meetings, a table a year. A row gives the date, the meeting, the
    # place and the time; its links say only "Agenda", "Agenda Part 1",
    # "Minutes" or "Download", so the row is read into each link's label.
    # Late agendas and agenda indexes sit beside some agendas and are not
    # them. The standing and budget committees are kept: they are on the
    # same page, so they cost nothing.
    pages = [
        # This year's table; in January it may still hold December's.
        ContentPage(_MEETINGS, holds=lambda y: y >= clock.current_year() - 1),
        ContentPage(
            f"{_MEETINGS}/Previous-Council-Meetings",
            holds=lambda y: y < clock.current_year(),
        ),
    ]

    def __init__(self):
        super().__init__("south_burnett", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        row = a.find_parent("tr")
        table = row.find_parent("table") if row else None
        if table is None:
            return label
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        cells = row.find_all("td", recursive=False)
        if len(headers) != len(cells):
            return label
        column = {h: c.get_text(" ", strip=True) for h, c in zip(headers, cells)}
        own = next((h for h, c in zip(headers, cells) if a in c.descendants), "")
        # The day column holds the weekday and date ("Wednesday 28 January
        # 2026"); older tables split them into Day and Date.
        date = column.get("date") or column.get("day", "")
        # "Special Meeting - Pound Street - to resume on at the conclusion
        # of ...": the meeting is the part before the first dash.
        meeting = re.split(r"\s+-\s+", column.get("meeting") or "Council Meeting")[0]
        # The time column sometimes says "to follow Special Council Meeting"
        # or "to resume on 1 March ..." instead.
        time = _TIME.search(column.get("time", ""))
        time = time.group() if time else ""
        filename = urlparse(a.get("href", "")).path.rsplit("/", 1)[-1]
        if (filename, meeting) in _WRONG_ROW:
            return None
        meeting = _ROW_MEETING.get(filename, meeting)
        if not _KIND.search(label):
            label = f"{own.title()} {label}"
        # A link that names its own meeting ("Agenda - General meeting -
        # Part 1" in the 15 July 2020 budget meeting's row) is that meeting's.
        if _MEETING.search(label):
            label = _MEETING.sub("Meeting", label)
            return f"{date} {time} - {label}"
        return f"{meeting} - {date} {time} - {label}"
