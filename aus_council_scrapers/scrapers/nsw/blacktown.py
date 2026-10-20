"""Blacktown City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Blacktown files one meeting as several listing rows, each its own "meeting
type" with its own payload, and only two of them hold the meeting's papers:

* **"Agenda of the Ordinary Meeting of Council"** (and "... Extraordinary
  Meeting of Council"): one file, titled "1.1 Agenda" (once, in June 2021,
  "1.1 Combined Index").
* **"Minutes of the Ordinary Meeting"** (and "Minutes of Extraordinary
  Meeting"): one file, titled "1.1 Combined Index"—which is the minutes,
  despite the name ("MINUTES of the ORDINARY MEETING ... 7 December
  2022")—or, since mid-2026, "1.1 Minutes of Ordinary Meeting".
* The bare **"Ordinary Council Meeting"** and **"Extraordinary Council
  Meeting"** rows hold the meeting's item reports, a PDF each, and no agenda.
  Neither do the standing committees (Planning, Development, Historical &
  Assets; Finance & Resources; and so on): their rows are item reports too,
  and their minutes go to Council as an item of its agenda. The Committee of
  the Whole has an agenda row but is neither a Council meeting nor a planning
  body. None of those rows is fetched—each would cost a request for nothing
  this scraper can store.

So the four paper rows are read as four listings, each filtered by meeting
type (``dd_OC Meeting Type``), and each payload's one file is taken as the
agenda or the minutes according to the row it came from. Rows for the same
meeting share a date, and the base class merges an agenda-only record and a
minutes-only record of the same name and date into one. Early 2021 meetings
have a minutes row and no agenda row, and are reported with minutes only.

**The year filter is not used.** It misses most meetings: for 2025 it returns
2 of the 11 "Minutes of the Ordinary Meeting" rows the listing holds, and in
October 2026 its 2026 results stopped at 7 October while the listing ran to
21 October. The type-filtered listings are paged newest first instead, and
stop once a page predates the wanted years. The listing reaches back to
February 2021; papers before May 2018 are on a separate Domino site that is
not read.

**What this costs.** One production year is four listing first pages (plus a
second page of the ordinary agendas late in the year) and one payload per
paper row: 27 requests and 54 s for 2026, measured in October 2026 (41
requests for all of 2025). That is above the 20 aimed for, and it is the
floor for this council, since each meeting's agenda and minutes are two
payloads; the allowlist is already down to Council's own meetings.
Recording the whole history is about 190 requests.

**The agenda is an index.** The file the council files as the agenda ("1.1
Agenda") is the Order of Business: one or two pages of item titles and page
numbers, with no reports. The reports themselves—including the Planning,
Development, Historical & Assets Committee's—are separate PDFs, one per item,
in the bare "Ordinary Council Meeting" row, which is not fetched. The minutes
are the full minutes. So a reader of `agenda_url` gets what is on the agenda,
not the planning reports behind it.

The location is left empty: it appears only in a sentence ("Monday 13 July,
2026 at Council Chambers, Civic Centre, Blacktown at 6:30pm."), not the
address block the base class reads.

**AM times are dropped.** Six payloads say 06:30 AM, in both the time field
and that sentence, and in each case the other row for the same meeting says
06:30 PM: the 25 March 2026 agenda row says AM and its minutes row PM, and
the 3 June 2026 agenda PDF itself reads "commencing at 6.30 p.m.". Every
meeting in the listing is held in the evening. So an AM time is taken as the
council's slip and left empty, and the merge fills it from the paired row's
PM time. A meeting whose only row says AM reports no time rather than a
wrong one.
"""

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    Listing,
    ListingRow,
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
)

_LISTING_URL = (
    "https://www.blacktown.nsw.gov.au"
    "/About-Council/How-we-work/Council-meetings-and-business-papers"
)
_LIST_NAME = "OC CL Public Meetings"

# The meeting types that carry papers, exactly as the type filter offers them.
_ORDINARY_AGENDA = "Agenda of the Ordinary Meeting of Council"
_ORDINARY_MINUTES = "Minutes of the Ordinary Meeting"
_EXTRAORDINARY_AGENDA = "Agenda of the Extraordinary Meeting of Council"
_EXTRAORDINARY_MINUTES = "Minutes of Extraordinary Meeting"

# The one file a paper row holds, by its title ("1.1 Agenda", "1.1 Combined
# Index", "1.1 Minutes of Ordinary Meeting"). Matched rather than assumed, so
# a row that one day carries a supplementary agenda beside the agenda does
# not report whichever was listed first. "Combined Index" is whichever paper
# its row is: the 28 June 2021 extraordinary meeting's agenda row holds one,
# and it is that meeting's agenda.
_AGENDA_TITLE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?(?:agenda|combined index)$", re.IGNORECASE
)
_MINUTES_TITLE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?(?:combined index|minutes\b.*)$", re.IGNORECASE
)


def _type_listing(meeting_type: str) -> Listing:
    return Listing(
        _LISTING_URL,
        _LIST_NAME,
        filters=f"(dd_OC%20Meeting%20Type={quote(meeting_type)})",
        by_year=False,
        required=True,
    )


@register_scraper
class BlacktownScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 55 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 55

    list_name = _LIST_NAME

    def __init__(self):
        super().__init__("blacktown", "NSW", _LISTING_URL)

    def main_listing(self) -> Listing:
        return _type_listing(_ORDINARY_AGENDA)

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            _type_listing(t)
            for t in (_ORDINARY_MINUTES, _EXTRAORDINARY_AGENDA, _EXTRAORDINARY_MINUTES)
        ]

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        role = "agenda" if row.meeting_type.startswith("Agenda") else "minutes"
        wanted = _AGENDA_TITLE if role == "agenda" else _MINUTES_TITLE

        titled = []
        for document in content.find_all("div", class_="meeting-document"):
            title_div = document.find("div", class_="meeting-document-title")
            anchor = next(
                (a for a in document.find_all("a", href=True) if _is_pdf(a["href"])),
                None,
            )
            if title_div and anchor:
                titled.append(
                    (
                        _label(title_div.get_text(" ", strip=True)),
                        anchor["href"].strip(),
                    )
                )

        for title, href in titled:
            if wanted.match(title):
                return {role: urljoin(self.base_url, href)}
        if titled:
            # Say what was passed over: a new title for the same paper should
            # be added above, not discovered later as a meeting gone missing.
            self.logger.warning(
                f"{row.date} {row.meeting_type}: no {role} among its files "
                f"{[t for t, _ in titled]}"
            )
        return {}

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record and record.time and "AM" in record.time.upper():
            # The council's slip for 6:30 PM (see the module docstring). Left
            # empty, the merge fills it from the meeting's other row; kept,
            # it would win, since the merge keeps the first row's time.
            record.time = None
        return record

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        # The row's type names the paper; the record is the meeting. Agenda
        # and minutes rows must come out with the same name to be merged.
        if "Extraordinary" in row.meeting_type:
            return "Extraordinary Council Meeting"
        return "Ordinary Council Meeting"
