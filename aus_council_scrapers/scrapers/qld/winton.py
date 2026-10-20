import calendar
import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.winton.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"

# "24.07 Minutes Special Meeting 31 7 2024 JULY signed": a numeric date.
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2}) (\d{1,2}) (20\d{2})(?!\d)")


@register_scraper
class WintonScraper(OpenCitiesContentScraper):
    # Three pages with an accordion per year: business papers (agendas)
    # from 2020, minutes from 2022, and an archive of minutes to 2021.
    # Each label starts with the year and month ("26.07 Business Paper
    # JULY", "26.07 Minutes 27 JULY SPECIAL"), and only special meetings
    # ever give a day, in the label or the file. The ordinary meeting each
    # month gives its day nowhere on these pages and is left out, never
    # dated to the 1st, so this council has special meetings only until
    # the month-only meetings are decided. Late papers and correspondence
    # are not the agenda and are left out too.
    #
    # Robots.txt disallows only /MyCity/ and a few unrelated pages, and
    # sets no Crawl-delay. Two requests a night; the archive only for
    # 2021 and before.
    pages = [
        ContentPage(f"{_MEETINGS}/Business-Papers"),
        ContentPage(f"{_MEETINGS}/Council-Minutes", holds=lambda y: y >= 2022),
        ContentPage(
            f"{_MEETINGS}/Previous-Agendas-and-Minutes", holds=lambda y: y <= 2021
        ),
    ]
    # Only special meetings give a day, so a year has no meeting until its
    # first one (26 July in 2024, 31 March in 2025, 30 April in 2026).
    # Until then the year raises rather than returning nothing as if it
    # were quiet.
    month_only_fails = True

    def __init__(self):
        super().__init__("winton", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        def numeric(m: re.Match) -> str:
            month = int(m.group(2))
            if not 1 <= month <= 12:
                return m.group(0)
            return f"{m.group(1)} {calendar.month_name[month]} {m.group(3)}"

        # The leading year and month, "25.02" or "2001": in "25.02 February
        # Minutes and Budget" the 02 would read as the 2nd.
        label = re.sub(r"^\s*\d{2}\.?\d{1,2}\b\.*\s*", "", label)
        label = _NUMERIC_DATE.sub(numeric, label)
        # "SPECIAL" and "(signed)" are how the label is typed, not the name.
        label = re.sub(r"\(?\bsigned\b\)?", " ", label, flags=re.IGNORECASE)
        label = re.sub(r"\bSPECIAL\b", "Special", label)
        label = re.sub(r"\bSpecial Council Meeting\b", "Special Meeting", label)
        # "25.03 Special Council Meeting 31 MARCH 2025" is filed among the
        # business papers and says nothing else about which paper it is.
        if "/business-papers/" in a.get("href", "") and not re.search(
            r"\b(?:business\s+papers?|agenda|minutes)\b", label, re.IGNORECASE
        ):
            label = f"{label} Business Paper"
        return label
