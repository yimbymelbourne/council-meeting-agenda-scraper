import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.meeting_documents import AGENDA, MINUTES
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.mapoon.qld.gov.au"

# Typed labels: "May 2025 Ordiniary Council Meeting Agenda", "March 2025
# Ordinatry Coucnil Meeting Minutes", "august_council_meeting_minutes_2024_
# conirmed". Left alone, a misspelt name is a meeting of its own, apart from
# its other paper. "MASC" is the council's initials.
_TYPOS = [
    (re.compile(r"\bordin\w*ry\b", re.IGNORECASE), "Ordinary"),
    (re.compile(r"\bcoucnil\b", re.IGNORECASE), "Council"),
    (re.compile(r"\bconirmed\b", re.IGNORECASE), "Confirmed"),
    (re.compile(r"\bageneda\b", re.IGNORECASE), "Agenda"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special"),
    (re.compile(r"\bMASC\b"), ""),
]


@register_scraper
class MapoonScraper(OpenCitiesContentScraper):
    # Two OpenCities content pages, agendas (from 2021) and minutes (from
    # 2017), an accordion per year. Papers are labelled by month
    # ("February-2026-Ordinary-Council-Meeting-Agenda.pdf", "September
    # 2025 Ordinary Council Meeting.pdf"), so the day is read from the PDF
    # (`pdf_dates`): the minutes first, 0.2-0.8 MB with the heading
    # "MINUTES Ordinary Council Meeting Thursday, 19 February 2026" up
    # front, and the agenda, 3-38 MB, only for a meeting with no minutes
    # yet. Its cover is usually in the first bytes.
    pages = [
        ContentPage(f"{_BASE_URL}/Council/Council-Meetings/Council-Agendas"),
        ContentPage(f"{_BASE_URL}/Council/Council-Meetings/Council-Minutes"),
    ]
    pdf_dates = True
    pdf_kinds = (MINUTES, AGENDA)
    month_only_fails = True

    # One production year: two pages and about one PDF read per meeting.
    expected_seconds = 30.0

    def __init__(self):
        super().__init__("mapoon", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        # "Special Council Meeting 13 September 2023" under Minutes is
        # "notice_of_special_meeting_13th_of_september_2023.pdf".
        filename = urlparse(a.get("href", "")).path.rsplit("/", 1)[-1]
        if re.match(r"notice", filename, re.IGNORECASE):
            return None
        for wrong, right in _TYPOS:
            label = wrong.sub(right, label)
        return label
