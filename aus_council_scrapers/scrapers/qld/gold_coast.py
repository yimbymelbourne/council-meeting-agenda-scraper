"""City of Gold Coast—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing (``OC CL Public Meetings``) carries every committee, about 90
meetings a year, back to mid-2020. Each meeting also has its own page, but the
rows carry a ``data-cvid`` and the renderer payload holds the same papers as
that page—about 2 KB against 175 KB—so this is the standard payload-per-meeting
shape, not ``detail_pages``. The meeting's page is still the record's
``webpage_url``, since it is where a reader finds those papers.

The listing honours ``(pagesize=N)``, so a whole year is one request; 2021,
the busiest year, has 123 rows. That leaves the payloads as the cost, so only
two kinds of meeting are fetched (``meeting_types``):

* **Council**—the ordinary meetings, and Special Council Meetings (SCM),
  which is where the budget is adopted.
* **Planning bodies**—Planning & Regulation (P&R) since 2024, Planning &
  Environment (P&E) before it, and the older names the type filter still
  offers: City Planning (CP), Economy, Planning & Environment (EP&E) and City
  Plan 2015 Special (CPS). None of those three has a meeting since 2020.

Left out are the Special Budget (SB) committee—budget workshops, seven in
2026, whose decisions go to a Special Council Meeting that is fetched—and the
portfolio committees (GA&F, ET&E, LEH&R, T&I, WW&E and their predecessors).
For 2026 that is 25 payloads of 82 rows, plus one listing page.

Papers are titled in a ``div.meeting-document``, by an ``<h3>`` since 2024 and
by a ``div.meeting-document-title`` before. The title repeats the meeting's
own name in front of the paper's, with or without a separator, and the
wording drifts by year:

* "Round 871 15 September 2026 Council Meeting - Supplementary Agenda"
* "Round 853 03 October 2023 P&E Committee agenda"
* "Round 819 Council 14 June 2022 confirmed minutes"
* "Round 803 03 June 2021 P&E Committee confirmed minutes part 1"

So a title is classified by the words in it (`papers`), not by how it
starts. Supplementary agendas, attachment books, one item's paper ("item 9.1 -
NAYBA Impact Audit", November 2022), notices (of meeting, cancellation,
change of date or time) and the budget documents filed beside a budget
adoption agenda are passed over. A paper split into parts is reported by its
first part. Confirmed minutes win over unconfirmed ones.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _NOT_THE_PAPER,
    _ONE_ITEM,
    _is_pdf,
    _label,
    _pick,
    _papers,
)

_COUNCIL_AND_PLANNING = re.compile(
    r"^(?:Council|Special Council Meetings"
    r"|Planning & Regulation|Planning & Environment"
    r"|Economy, Planning & Environment|City Planning|City Plan 2015 Special)\b"
)

# The listing's types, as meeting names. Types not here are used as listed.
_NAMES = {
    "Council": "Council Meeting",
    "Special Council Meetings (SCM)": "Special Council Meeting",
    "Planning & Regulation (P&R)": "Planning & Regulation Committee",
    "Planning & Environment (P&E)": "Planning & Environment Committee",
}

_AGENDA = re.compile(r"\bagendas?\b", re.IGNORECASE)
# Some titles are cut off mid-word: "Confirmed Minut", "Confirmed Min". In
# August and September 2020 the P&E Committee's minutes are its "adopted
# report"—the committee reported to Council, which adopted it—and the same
# paper is "adopted minutes" from October 2020 on.
_MINUTES = re.compile(
    r"\bminut\w*|\bconfirmed\s+min\w*|\badopted\s+report\b", re.IGNORECASE
)

# Filed beside the papers, never the papers themselves.
_NOT_A_PAPER = re.compile(
    r"\bnotice\b|\bnotification\b|cancel|\bchange\s+of\b|\breschedul"
    r"|\border\s+of\s+business\b|\bmemorandum\b",
    re.IGNORECASE,
)

# Minutes bound with their attachments are still the minutes: "SC Meeting -
# Confirmed Minutes & Attachments" (Special Council, 15 April 2024), where
# "agenda attachments" on its own is an attachment book.
_WITH_ATTACHMENTS = re.compile(
    r"\s*(?:and|&)\s+(?:minute\s+item\s+)?attachments?\b", re.IGNORECASE
)

_PART = re.compile(r"\bpart\s*(\d+)\b", re.IGNORECASE)

# Listing rows whose date is wrong, by cvid. The 798th Council meeting is
# listed as 15 February 2021, but its only paper is "Council Meeting 16
# February 2021 - minutes" and the minutes open "held Tuesday 16 February
# 2021 at 10am". It is the only row in 2020-2026 whose paper titles give a
# different date from the row, so it is corrected here rather than by
# preferring title dates in general: a rescheduled meeting can keep the old
# date in its paper titles while the row gives the real one.
_DATE_FIXES = {
    "95934fe8-b0bb-4571-bdeb-c1451463172e": "16 February 2021",
}


def _title(section) -> str:
    element = section.find("h3") or section.find("div", class_="meeting-document-title")
    return _label(element.get_text(" ", strip=True)) if element else ""


@register_scraper
class GoldCoastScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 54 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 54

    list_name = "OC CL Public Meetings"
    page_size = 200
    meeting_types = _COUNCIL_AND_PLANNING

    def __init__(self):
        super().__init__(
            "gold_coast",
            "QLD",
            "https://www.goldcoast.qld.gov.au/Council/Council-meetings/Minutes-agendas",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        agendas: list[tuple[str, str, int]] = []
        minutes: list[tuple[str, str, int]] = []
        for section in content.find_all("div", class_="meeting-document"):
            title = _title(section)
            if (
                not title
                or _NOT_THE_PAPER.search(_WITH_ATTACHMENTS.sub("", title))
                or _ONE_ITEM.search(title)
                or _NOT_A_PAPER.search(title)
            ):
                continue
            part = _PART.search(title)
            if part and int(part.group(1)) > 1:
                continue
            url = next(
                (
                    a["href"].strip()
                    for a in section.find_all("a", href=True)
                    if _is_pdf(a["href"].strip())
                ),
                None,
            )
            if not url:
                continue
            candidate = (title, urljoin(self.base_url, url), 1 if part else 0)
            # Minutes first: no title names both, but "minutes" is the more
            # specific word.
            if _MINUTES.search(title):
                minutes.append(candidate)
            elif _AGENDA.search(title):
                agendas.append(candidate)
        return _papers(_pick(agendas), _pick(minutes))

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        sections = content.find_all("div", class_="meeting-document")
        titles = [t for t in (_title(s) for s in sections) if t]
        if titles and all(_NOT_A_PAPER.search(t) for t in titles):
            # A cancelled meeting keeps its row and files only the notice.
            # Nothing to report, and nothing the base class should warn about.
            return None
        record = super().build_return(content, row)
        if record is not None:
            record.name = _NAMES.get(row.meeting_type, row.meeting_type)
            record.webpage_url = row.detail_url or row.webpage_url
            record.date = _DATE_FIXES.get(row.cvid, record.date)
        return record
