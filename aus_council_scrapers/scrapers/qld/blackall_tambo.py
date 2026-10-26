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
    # give their day nowhere on the page and are left out, never dated to
    # the 1st. Late agenda items and the delegations registers filed among
    # the agendas are not the agenda and are left out too.
    #
    # Robots.txt disallows only image and banner pages, none under
    # /Council/Council-Meetings or /files/, and sets no Crawl-delay. Two
    # requests a night.
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
    }

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
