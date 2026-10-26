import calendar
import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.meeting_documents import AGENDA, MINUTES
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.carpentaria.qld.gov.au"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
# "01 January 2026 Confirmed Minutes", "01_January-2026-Business-Paper.pdf":
# the leading number is the month's, not a day.
_MONTH_NUMBER = re.compile(
    r"^\s*(\d{1,2})[\s_.-]+(?=(" + "|".join(_MONTHS) + r")\b)", re.IGNORECASE
)


@register_scraper
class CarpentariaScraper(OpenCitiesContentScraper):
    # Two OpenCities content pages, agendas and minutes, an accordion per
    # year from 2020 (minutes from 2017). Every paper is labelled by month
    # alone, led by the month's number ("01 January 2026 Confirmed Minutes",
    # "06 June 2026 Budget Business Paper"), so the day is read from the PDF
    # (`pdf_dates`). The business paper first: its cover ("BUSINESS PAPER
    # 22 JANUARY, 2025") is in the first 256 KB of a 3-68 MB file. The
    # confirmed minutes, 4-14 MB, are scans with no text, so a file that
    # cannot be read from its first bytes is not downloaded whole past 2 MB;
    # the unconfirmed minutes (a few hundred KB) do have text.
    # The council meets on a Wednesday and, if needed, the Thursday after;
    # the cover gives the Wednesday. Late business papers are not the agenda.
    pages = [
        ContentPage(f"{_BASE_URL}/Council/Council-Meetings/Council-Agendas"),
        ContentPage(f"{_BASE_URL}/Council/Council-Meetings/Council-Minutes"),
    ]
    numbered_files = True
    pdf_dates = True
    pdf_kinds = (AGENDA, MINUTES)
    pdf_full_limit = 2 * 1024 * 1024
    month_only_fails = True

    # One production year: two pages and about one PDF read per meeting.
    expected_seconds = 30.0

    def __init__(self):
        super().__init__("carpentaria", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # The 2026 links are titled with the filename
        # ("01_January-2026-Business-Paper.pdf").
        label = re.sub(r"[_-]+", " ", label)
        m = _MONTH_NUMBER.match(label)
        if m and int(m.group(1)) == _MONTHS[m.group(2).lower()]:
            label = label[m.end() :]
        return label
