import datetime
import re

from bs4 import Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.torres.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"


@register_scraper
class TorresScraper(OpenCitiesContentScraper):
    # Four pages: this year's agendas and this year's minutes, each a page
    # named for the year ("2026-Meeting-Agendas"), and two archives with an
    # accordion per year (agendas from 2023, minutes from 2010). The year
    # pages are found from the Council Meetings page rather than built from
    # the year, since they are renamed each January.
    #
    # This year's labels give only the month ("January Ordinary Meeting
    # Agenda with Attachments"); the day is in the filename
    # ("27jan2026-agenda-ocm-...", "...-minutes-27-january-2026.pdf"), and
    # the page title gives the year. The 2024–25 agendas name only the
    # month in their files too, and take the day of the same meeting's
    # minutes. The ordinary minutes of 2020 give no day anywhere on the
    # page, and are dated from their PDFs in `misfiled`. Agendas before 2023
    # are not online, so earlier years are minutes only.
    year_index = _MEETINGS
    year_page = re.compile(
        r"/Council/Council-Meetings/(?P<year>\d{4})-Meeting-(?:Agendas|Minutes)$"
    )
    page_headings = ("h1",)
    pages = [
        ContentPage(
            f"{_MEETINGS}/Archived-Meeting-Agendas",
            holds=lambda y: y < clock.current_year(),
        ),
        ContentPage(
            f"{_MEETINGS}/Archived-Meeting-Minutes",
            holds=lambda y: y < clock.current_year(),
        ),
    ]

    misfiled = {
        # "01 - January 2020 Meeting Minutes Confirmed" and its neighbours:
        # the filename's leading number is the month's place in the year,
        # which reads as the day (1 January, 2 February, 3 March, 4 April).
        # Each PDF is headed "MINUTES OF THE ORDINARY MEETING ... HELD ...
        # ON THURSDAY ISLAND" on the date given here.
        "01___january_2020_meeting_minutes_confirmed.pdf": datetime.date(2020, 1, 28),
        "02___february_2020_meeting_minutes_confirmed.pdf": datetime.date(2020, 2, 18),
        "03___march_2020_meeting_minutes_confirmed.pdf": datetime.date(2020, 3, 17),
        "04___april_2020_meeting_minutes_confirmed.pdf": datetime.date(2020, 4, 30),
        # "08 - August 2020 Meeting Minutes Confirmed" to December: month
        # only, in the label and the file. Each PDF is headed "... HELD IN
        # COUNCIL CHAMBERS ... TUESDAY" on the date given here.
        "minutes_august_2020___confirmed.pdf": datetime.date(2020, 8, 18),
        "minutes_september_2020___confirmed.pdf": datetime.date(2020, 9, 15),
        "minutes_october_2020___confirmed.pdf": datetime.date(2020, 10, 20),
        "minutes_november_2020___confirmed.pdf": datetime.date(2020, 11, 17),
        "minutes_december_2020___confirmed.pdf": datetime.date(2020, 12, 8),
    }

    def __init__(self):
        super().__init__("torres", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # A month's sequence number, "12 - December 2020 Meeting Minutes",
        # would read as the 12th.
        label = re.sub(r"^\s*\d{1,2}\s+[-–|]\s+", "", label)
        # The 2025 minutes are filenames ("28-JAN-2025-Minutes-OCM-
        # Confirmed.pdf") and the 2024–25 agendas "... Agenda Papers"; say
        # both as the other papers do, so a month-only agenda can take the
        # day of its minutes.
        if not re.search(r"\s", label):
            label = label.replace("-", " ")
        label = re.sub(r"\bOCM\b", "Ordinary Council Meeting", label)
        # "February SPECIAL Meeting Agenda".
        label = re.sub(r"\b(SPECIAL|BUDGET)\b", lambda m: m.group(1).title(), label)
        # This year's labels say "Ordinary Meeting" and "Special Meeting",
        # 2021–25's "Ordinary Council Meeting" and "Special Council
        # Meeting"; one name for each meeting type.
        label = re.sub(
            r"\b((?:Ordinary|Special)(?: Budget)?) Meeting\b", r"\1 Council Meeting", label
        )
        # "January 2020 Meeting Minutes": the ordinary meeting, its PDF says.
        label = re.sub(
            r"\b(\d{4}) Meeting Minutes\b",
            r"\1 Ordinary Council Meeting Minutes",
            label,
        )
        label = re.sub(r"\bagenda\s+papers\b", "Agenda", label, flags=re.IGNORECASE)
        # "Agenda and Business Papers 1/2": part one is the agenda proper.
        return re.sub(r"\s(\d)/\d\b", r" Part \1", label)
