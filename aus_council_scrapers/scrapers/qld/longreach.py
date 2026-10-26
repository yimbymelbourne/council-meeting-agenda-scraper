import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.longreach.qld.gov.au"

# A year heading above a table: "2026" in an h3, or in a p for 2024.
_YEAR_HEADING = re.compile(r"^\s*(20\d{2})\s*$")
# What a row's link says besides its month: "February (Special)",
# "June (Special - Budget)", "March - Post Election Meeting", "July - Part 1".
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_BUDGET = re.compile(r"\bbudget\b", re.IGNORECASE)
_POST_ELECTION = re.compile(r"\bpost[\s-]*election\b", re.IGNORECASE)
_PART = re.compile(r"\bpart\s*\d+\b", re.IGNORECASE)
_MONTH_ONLY = re.compile(
    r"^\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.IGNORECASE
)


@register_scraper
class LongreachScraper(OpenCitiesContentScraper):
    # One page, a table per year from 2022 under a heading that is only the
    # year (an h3, or for 2024 a p; the 2025 table's cell ids say "2024",
    # so the heading is what decides). Columns Agenda, Late Items and
    # Minutes; a row per meeting, and every link in it says only the month
    # ("October", "February (Special)", "March - Post Election Meeting").
    # So a link is read as its row's meeting, its column's paper and its
    # table's year, and the day comes from the filename
    # ("ordinary-council-meeting-15-oct-2026_compressed.pdf",
    # "2023_08_17_agenda.pdf", "co_17112022_agn_910_at_new.pdf"), or from
    # the other paper of the same meeting when only one file has it
    # ("march_ordinary_council_meeting_minutes.pdf" beside
    # "20_march_ordinary_council_meeting_agenda_2025.pdf"). A meeting whose
    # files give no day is left out, never dated to the 1st.
    #
    # The Late Items column is left out: those are supplementary papers,
    # not the agenda. Standing committees are on another page, and the
    # council keeps nothing before 2022 online.
    #
    # Robots.txt disallows nothing under /About-Council or /files/ and sets
    # no Crawl-delay. One request a night.
    pages = [
        ContentPage(
            f"{_BASE_URL}/About-Council/Council/Our-Meeting-Minutes-and-Agendas"
        )
    ]

    def __init__(self):
        super().__init__("longreach", "QLD", _BASE_URL)

    @staticmethod
    def _table_year(table: Tag) -> Optional[str]:
        for el in table.find_all_previous(["h2", "h3", "h4", "p"]):
            m = _YEAR_HEADING.match(el.get_text(" ", strip=True))
            if m:
                return m.group(1)
        return None

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        cell, table = a.find_parent(["td", "th"]), a.find_parent("table")
        if cell is None or table is None:
            # The meeting schedule above the tables.
            return None
        if not _MONTH_ONLY.match(label):
            # "Item 14.2 Attachments" in the December 2022 agenda cell keeps
            # its words, so the base leaves it out.
            return label
        row = cell.find_parent("tr")
        cells = row.find_all(["td", "th"])
        header = [
            c.get_text(" ", strip=True) for c in table.find("tr").find_all(["td", "th"])
        ]
        column = next((i for i, c in enumerate(cells) if c is cell), None)
        year = self._table_year(table)
        if column is None or column >= len(header) or year is None:
            return None
        paper = header[column]
        month = _MONTH_ONLY.match(label).group(0).strip()
        if _POST_ELECTION.search(label):
            meeting = "Post Election Meeting"
        elif _SPECIAL.search(label):
            meeting = (
                "Special Budget Meeting" if _BUDGET.search(label) else "Special Meeting"
            )
        else:
            meeting = "Ordinary Council Meeting"
        part = _PART.search(label)
        part = f" {part.group(0)}" if part else ""
        # "Late Items" keeps its words, so the base leaves those papers out.
        # The part goes last: "Part 1 - July 2023" would read as 1 July.
        return f"{meeting} - {paper} - {month} {year}{part}"
