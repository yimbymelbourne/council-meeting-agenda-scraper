"""Shared fixes for eight regional Victorian councils on OpenCities.

Mildura, Surf Coast, Campaspe, Moira, Colac Otway, Swan Hill, Mount Alexander
and Horsham all run the standard OpenCities meetings module, so each is a
`OpenCitiesMeetingsScraper` subclass. Checked against every payload recorded
in October 2026, they share three things the base class does not do, and
those live here rather than eight times over:

* **The same listing settings.** Every one honours ``(pagesize=N)``, so a
  year is one listing request, and every one carries the full year dropdown
  on a year-filtered page (checked 20 Oct 2026), so production can start from
  that page. Moira and Mount Alexander name their list
  ``OC CL Public Past Meetings``; the others ``OC CL Public Meetings``.
* **A listing date that is sometimes wrong.** Three rows disagree with both
  the meeting's own page address and its papers: Mildura lists its 25
  August 2022 Ordinary Meeting as 24 August, Swan Hill its 4 November 2021
  Unscheduled Meeting as 16 November, and Mount Alexander its 17 March 2020
  Council Meeting as 16 March. `meeting_date`
  trusts the page address only when the papers back it and say nothing for
  the listing's date. Campaspe's 18 April 2023 meeting has a page address of
  ``18-August-2023`` and papers saying 18 April, so it keeps its listing date.
* **The meeting's page as the record's webpage.** Each row links one, and it
  costs nothing: the papers still come from the renderer payload.
* **Meetings that never ran.** A cancelled or postponed meeting keeps its
  row, and sometimes its agenda too, with a note at the top of the payload
  saying so. Four in the October 2026 recordings still had an agenda:
  Horsham 23 March 2020 ("(CANCELLED)"), Colac Otway 25 March 2020
  ("cancelled for reasons related to COVID-19"), Mildura's 10 March 2022
  Planning Delegated Committee ("All Agenda Items have been removed … the
  meeting has been cancelled") and Campaspe 19 October 2022 ("POSTPONED UNTIL
  FURTHER NOTICE"). The base class would report each as a meeting held on
  that day, so `build_return` skips any row whose note says it was
  cancelled or postponed, as Knox's scraper does. The others (Moira 26
  October 2022, Mount Alexander 21 April 2020, Mildura 12 September 2024)
  carry no papers and were skipped already.

`split_off` is for a row that carries another meeting's papers: Campaspe's
17 November 2021 and Mount Alexander's 18 November 2025 hold two meetings'
papers, and Mount Alexander's 26 November 2024 only the other meeting's.
"""

from __future__ import annotations

import datetime
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
)

# The last segment of a meeting page's address: "25-August-2022-Ordinary-
# Council-Meeting", "4-November-2021". Typos ("15-Decmeber-2020") and
# addresses with no date ("Tuesday-17-December-Council-Meeting") give no date,
# and then the listing's date stands.
_SLUG_DATE = re.compile(r"(?<!\d)(\d{1,2})-([A-Za-z]+)-((?:19|20)\d\d)(?!\d)")


def _slug_date(url: str) -> Optional[datetime.date]:
    last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = _SLUG_DATE.search(last)
    if not match:
        return None
    try:
        return parse_date(" ".join(match.groups())).date()
    except (ValueError, OverflowError):
        return None


def _paper_text(content: BeautifulSoup) -> str:
    """Every PDF's label and filename, lower-cased, with separators as
    spaces, so one search covers "25 August 2022" and "25-august-2022"."""
    parts = []
    for anchor in content.find_all("a", href=True):
        href = anchor["href"].strip()
        if not _is_pdf(href):
            continue
        parts.append(_label(anchor.get_text(" ", strip=True)))
        parts.append(urlparse(href).path.rsplit("/", 1)[-1])
    text = " ".join(parts).lower()
    return re.sub(r"[-_.]+", " ", text)


def _mentions(text: str, day: datetime.date) -> bool:
    month = day.strftime("%B").lower()
    forms = [
        rf"\b0?{day.day} {month} {day.year}\b",
        rf"\b{day.day:02d}{day.month:02d}{day.year}\b",
        rf"\b{day.year} {day.month:02d} {day.day:02d}\b",
    ]
    return any(re.search(form, text) for form in forms)


# The note at the top of a payload: "23 March 2020 Ordinary Council Meeting
# (CANCELLED)", "THIS MEETING HAS BEEN POSTPONED UNTIL FURTHER NOTICE",
# "Please note this meeting is no longer going ahead". Only that note is
# read. Page addresses are not: Swan Hill's 23 February 2021 meeting, which
# was held, lives at "23-February-2021-Postponed-from-16-February-2021". Nor
# are paper labels: Mildura's "Public Notice - Cancelled …" PDFs are notices
# beside a payload that says so in its note anyway. "Postponed from" is the
# meeting that was held.
_NEVER_RAN = re.compile(
    r"\bcancell?ed\b|\bpostponed\b(?!\s+from)|\bno longer going ahead\b",
    re.IGNORECASE,
)


def never_ran(content: BeautifulSoup) -> Optional[str]:
    """The payload note saying a row's meeting did not run, or None. See
    the module docstring."""
    container = content.find("div", class_="meeting-container") or content
    for note in container.find_all("p", recursive=False):
        text = note.get_text(" ", strip=True)
        if _NEVER_RAN.search(text):
            return text
    return None


def meeting_date(row: ListingRow, content: BeautifulSoup, logger) -> str:
    """The row's date, unless its meeting page and its papers agree on
    another one. See the module docstring for the rows this decides."""
    try:
        listed = parse_date(row.date, dayfirst=True).date()
    except (ValueError, OverflowError):
        return row.date
    from_slug = _slug_date(row.detail_url) if row.detail_url else None
    if from_slug is None or from_slug == listed:
        return row.date
    text = _paper_text(content)
    if _mentions(text, from_slug) and not _mentions(text, listed):
        logger.info(
            f"{row.date} {row.meeting_type}: its page and papers say "
            f"{from_slug:%d %B %Y}; using that date"
        )
        return from_slug.strftime("%d %B %Y")
    return row.date


class RegionalOpenCitiesScraper(OpenCitiesMeetingsScraper):
    """Not registered: the base for the eight councils above."""

    list_name = "OC CL Public Meetings"
    page_size = 50
    year_filtered_first_page = True

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        reason = never_ran(content)
        if reason:
            self.logger.info(
                f"{row.date} {row.meeting_type}: did not run ({reason[:80]!r}), "
                f"so it is skipped"
            )
            return None
        record = super().build_return(content, row)
        if record is None:
            return None
        record.date = meeting_date(row, content, self.logger)
        record.webpage_url = row.detail_url or row.webpage_url
        return record

    def split_off(
        self,
        content: BeautifulSoup,
        row: ListingRow,
        belongs: Callable[[BeautifulSoup], list],
        name: str,
    ) -> list[ScraperReturn]:
        """Records for a row whose payload also holds another meeting's
        papers.

        ``belongs(soup)`` returns the elements of a payload that belong to
        the other meeting—``div.meeting-document`` sections or PDF links.
        The row's own record is built from the payload without them, and a
        second record, named ``name``, from the payload with only them. A
        row holding only the other meeting's papers becomes that meeting.
        With nothing to split, this is the ordinary single record.
        """
        if not belongs(content):
            return super().build_returns(content, row)
        rest = BeautifulSoup(str(content), "html.parser")
        for element in belongs(rest):
            element.decompose()
        other = BeautifulSoup(str(content), "html.parser")
        kept = belongs(other)
        keep = {id(e) for e in kept}
        for element in _paper_elements(other):
            if element.decomposed or id(element) in keep:
                continue
            if any(id(parent) in keep for parent in element.parents):
                continue  # inside a kept section
            if any(p is element for k in kept for p in k.parents):
                continue  # holds a kept link
            element.decompose()
        records = []
        main = self.build_return(rest, row)
        if main is not None:
            records.append(main)
        split = self.build_return(other, row)
        if split is not None:
            split.name = name
            records.append(split)
        return records


def _paper_elements(soup: BeautifulSoup) -> list:
    """What can carry a paper: the titled sections and every PDF link.
    Sections are listed first so a kept section keeps its own links."""
    sections = soup.find_all("div", class_="meeting-document")
    links = [a for a in soup.find_all("a", href=True) if _is_pdf(a["href"].strip())]
    return sections + links
