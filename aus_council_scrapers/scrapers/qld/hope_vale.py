import datetime
import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import OpenCitiesContentScraper

_BASE_URL = "https://www.hopevale.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"

_PAPER_WORD = re.compile(r"agenda|minut|notice|business\s+paper", re.I)
_ONLY_A_MEETING = re.compile(
    r"^(?:(?:ordinary|special|council)\s+)+meeting\s*[-–]?\s*"
    r"(?:\d{1,2}(?:st|nd|rd|th)?\s+)?[a-z]+\s+\d{4}$",
    re.I,
)


@register_scraper
class HopeValeScraper(OpenCitiesContentScraper):
    # A page per year ("2026-Meetings", back to 2018), linked from the
    # Council Meetings page, with an accordion per meeting ("Council Meeting
    # January 2026"). Each holds the notice, the agenda, the meeting's own
    # minutes, the previous meeting's confirmed minutes and one PDF per
    # officer's report. The notice and reports are not the agenda and are
    # left out; a set of minutes listed under two meetings is one file, read
    # once.
    #
    # Agendas are often labelled by month only ("January Agenda 2026"); the
    # day is in the filename ("agenda-21st-january-2026.pdf") or the same
    # meeting's minutes ("Confirmed Minutes 18th February 2026"). A meeting
    # that gives its day nowhere is left out, never dated to the 1st.
    #
    # Robots.txt disallows nothing under /Council/Council-Meetings or
    # /files/ and sets no Crawl-delay. Two requests a night: the index and
    # the year's page.
    year_index = _MEETINGS
    year_page = re.compile(r"/Council/Council-Meetings/(?P<year>\d{4})-Meetings$")

    misfiled = {
        # "April Agenda 2023": the PDF is headed "ORDINARY COUNCIL MEETING
        # Monday 3rd April 2023", the date its minutes give ("Minutes 3rd
        # April 2023"), not the 5th its filename says.
        "agenda_5th_april_2023.pdf": datetime.date(2023, 4, 3),
    }

    def __init__(self):
        super().__init__("hope_vale", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # "Confirmed Council Minutes 18th/19th June 2024": a two-day
        # meeting, dated by its first day like its agenda ("Agenda 18 June").
        label = re.sub(r"(\d)(st|nd|rd|th)?\s*/\s*(\d)", r"\1\2 and \3", label)
        # "Confirmed Council Special Meeting Minutes" and "Confirmed Special
        # Council Meeting" are the "Special Meeting".
        label = re.sub(r"\bCouncil Special\b", "Special", label)
        label = re.sub(r"\bSpecial Council Meeting\b", "Special Meeting", label)
        # Some minutes never say "Minutes". "Confirmed Special Meeting 30th
        # August 2024", "Confirmed Council Special Meeting 6th February 2025"
        # and "Confirmed Special Council Meeting - 4th November" are each a
        # scan headed "Minutes", and "Ordinary Council Meeting - October
        # 2025", filed under November, is the signed minutes of 15 October
        # 2025. Only a "Confirmed" meeting, or a label that is a meeting and
        # a date and nothing else, is read this way: officers' papers that
        # name a meeting ("Director Social Services - Council Meeting -
        # August 2025", "Committee Meeting - Aged Care Quality") are not
        # minutes.
        if not _PAPER_WORD.search(label) and (
            re.search(r"\bconfirmed\b.*\bmeeting\b", label, re.I)
            or _ONLY_A_MEETING.match(label)
        ):
            label += " Minutes"
        return label
