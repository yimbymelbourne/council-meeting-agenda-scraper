import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.narrandera.nsw.gov.au"

# The meeting type a business paper's link starts with: "Ordinary - 20 Oct
# 2026", "Extraordinary - 5 May 2026", "Ordinary -17 Feb 2026".
_TYPE = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?)\s*-", re.IGNORECASE)
_BUSINESS_PAPER = re.compile(r"\bbusiness\s+papers?\b", re.IGNORECASE)


@register_scraper
class NarranderaScraper(OpenCitiesContentScraper):
    # One page, one table: a row per meeting from October 2024 (older
    # meetings are off the page, and nothing on the site links an archive),
    # with columns Date, Business Paper, Minutes and Attachments. The
    # business paper is the agenda, linked as the meeting type and the date
    # ("Ordinary - 20 Oct 2026"), sometimes with its late items beside it
    # ("Late items - 18 Aug 2026"); the minutes are "Minutes - 15 Sep 2026".
    # Only the column says which paper a link is and only the business paper
    # says which meeting, so each link is read as its row's meeting, its
    # column's paper and the row's date. The date comes from the row's own
    # cell, never the link: the 18 March 2025 minutes are linked as
    # "Minutes - 18 Mar 20".
    #
    # Robots.txt disallows nothing under /Council/Council-meetings or
    # /files/, and sets no Crawl-delay. One request a night.
    pages = [
        ContentPage(f"{_BASE_URL}/Council/Council-meetings/Business-papers-and-minutes")
    ]

    def __init__(self):
        super().__init__("narrandera", "NSW", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        row, table = a.find_parent("tr"), a.find_parent("table")
        if row is None or table is None:
            return None
        cells = row.find_all(["td", "th"])
        header = [
            c.get_text(" ", strip=True) for c in table.find("tr").find_all(["td", "th"])
        ]
        cell = a.find_parent(["td", "th"])
        column = next((i for i, c in enumerate(cells) if c is cell), None)
        if column is None or column >= len(header):
            return None
        paper, date = header[column], cells[0].get_text(" ", strip=True)
        if _BUSINESS_PAPER.search(paper):
            # This link names its own meeting. "Late items - 18 Aug 2026" is
            # in this column too, and keeps its words so the base leaves it
            # out.
            meeting = _TYPE.match(label)
        elif re.search(r"\bminutes\b", paper, re.IGNORECASE):
            # The minutes are the meeting's whose business paper shares the
            # row.
            papers = [
                link.get_text(" ", strip=True)
                for i, name in enumerate(header)
                if _BUSINESS_PAPER.search(name) and i < len(cells)
                for link in cells[i].find_all("a", href=True)
            ]
            meeting = next(
                (
                    m
                    for m in map(_TYPE.match, papers)
                    if m and not re.search(r"\blate\b", m.group(1), re.IGNORECASE)
                ),
                None,
            )
        else:
            # The Attachments column.
            return None
        kind = meeting.group(1).strip() if meeting else ""
        return f"{kind} Council Meeting - {paper} - {date}"
