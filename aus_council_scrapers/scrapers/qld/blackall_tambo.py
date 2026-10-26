import datetime
import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.btrc.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"


@register_scraper
class BlackallTamboScraper(OpenCitiesContentScraper):
    # Two pages with an accordion per year: agendas from 2018 ("Council
    # Meeting Agendas 2026") and minutes from 2017 ("2026 Meeting
    # Minutes"). Every label names only the month ("March 2026 Agenda",
    # "January Meeting Minutes 2026 Confirmed"); the day is in some
    # filenames ("general_meeting-18_march_2026_agenda.pdf",
    # "budget-meeting-17-june-2026-unconfirmed-minutes.pdf") and is shared
    # with the same meeting's other paper. Most meetings before April 2024
    # give their day nowhere on the page, and are dated from their papers'
    # first page instead (`pdf_dates`), the agenda first; a meeting neither
    # paper dates is left out, never dated to the 1st. Many agendas are
    # past 8 MB with their cover deep in the file, and the minutes are
    # often scans with no text, so a paper not readable from its first
    # bytes is downloaded whole only up to 2 MB: at the default 8 MB, three
    # undatable 2026 meetings cost about 26 MB a night. Late agenda items
    # and the delegations registers filed among the agendas are not the
    # agenda and are left out too.
    #
    # Robots.txt disallows only image and banner pages, none under
    # /Council/Council-Meetings or /files/, and sets no Crawl-delay. Two
    # page requests a night, plus a PDF read or two for each month-only
    # meeting of the year.
    pages = [
        ContentPage(f"{_MEETINGS}/Council-Meeting-Agendas"),
        ContentPage(f"{_MEETINGS}/Council-Meeting-Minutes"),
    ]

    # Most of a year's meetings give only their month, so a year can hold
    # papers and no meeting with a day; that raises rather than returning
    # nothing as if the year were quiet.
    month_only_fails = True

    misfiled = {
        # "2026/2027 Budget Meeting Agenda" names neither day nor month, in
        # its text or its file. The PDF is the "Agenda-Budget Meeting-17
        # June 2026", the date its minutes give.
        "2026-2027-budget_meeting-agenda.pdf": datetime.date(2026, 6, 17),
        # Month-only agendas whose cover is not in the first bytes and whose
        # file is 20-46 MB, past the 2 MB read below, with minutes that are
        # scans with no text. Each cover reads "GENERAL MEETING Wednesday 18
        # February 2026"; read once, 26 Oct 2026. The minutes join them.
        "november_2024_agenda.pdf": datetime.date(2024, 11, 20),
        "november-2025-agenda.pdf": datetime.date(2025, 11, 19),
        "february-2026-agenda.pdf": datetime.date(2026, 2, 18),
        "july-2026-agenda.pdf": datetime.date(2026, 7, 15),
        "general-meeting-agenda-september-2026.pdf": datetime.date(2026, 9, 16),
    }

    pdf_dates = True
    pdf_full_limit = 2 * 1024 * 1024

    def __init__(self):
        super().__init__("blackall_tambo", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # Labels typed as the filename ("May-Meeting-Minutes-2025-
        # Confirmed.pdf").
        if not re.search(r"\s", label):
            label = label.replace("-", " ")
        # The monthly meeting is the General Meeting ("general_meeting_-_
        # 21_january-2026-agenda.pdf"); the labels just say "Meeting" or
        # nothing. One name, so the agenda and minutes join.
        if not re.search(r"\b(?:budget|special|post[\s-]*election)\b", label, re.I):
            label = re.sub(r"\bMeeting\b\s*", "", label)
            label = f"General Meeting - {label}"
        return label
