"""Mid-Western Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list holds the Ordinary and Extraordinary Council meetings back to
2011, the only two types it offers, so nothing is allowlisted. Its internal
name is not the usual one: "Council Meetings - Agendas Listing", read off
the form ``action`` after a year-filter postback. The standard names are
ignored by the site, which then serves the unfiltered first page.

Rows for the rest of the year are listed in advance—18 November and 9
December 2026 were listed on 20 October with no papers yet—and are skipped
until their agenda is up.

Papers are filed under headings that carry the date: "Agenda 21 October
2026", "Confirmed Minutes 19 August 2026", "Unconfirmed Minutes 16 September
2026". All match the base class's start-anchored rules, and "Meeting Items",
"Separately Attached Attachments" and "Councillor Questions and Answers" are
passed over. Confirmed minutes replace the unconfirmed ones once adopted.

**A heading can link another meeting's paper.** "Agenda 14 August 2024"
links the 16 October 2024 business paper, from the 16 October folder
(``/council-meetings/old/2024/10.-16-october-2024/``)—its front page says
16 October. Each meeting's papers sit in a folder named for its date, so a
paper is dropped when its folder names another date and its file name does
not name the meeting's; 14 August 2024 then carries its minutes only.
Neither source is trusted alone. File names slip: the 13 October 2021
minutes are named "council-meeting-4-august-2021-confirmed-minutes.pdf" and
are the 13 October minutes, and the 31 January 2020 agenda is named for 2021
(both checked against the PDFs, October 2026). And papers re-published
later land in a later meeting's folder with their own date in their name:
9 December 2020's redacted business paper is in the 4 August 2021 folder,
and 26 March 2021's in the 21 July 2021 one.

**Most links before 2024 are dead.** The council moved its 2020–2023 meeting
folders under ``/council-meetings/old/`` and did not update the payloads:
in October 2026 all 40 such links on 2020–2022 meetings, and 12 of the 20
on 2023 ones, answered 404, and every one of them was served at the same
path with ``old/`` inserted—as were the 2023 links that still worked.
So papers from those years are reported at the ``old/`` path (`_moved`).
2024 onwards answer where they are linked.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per listed meeting: 14 for 2026.
"""

import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

# "10.-16-october-2024", "12.13-october-2021": the meeting's number in the
# year, then its date.
_FOLDER_DATE = re.compile(
    r"^\d+\.\s*-?(\d{1,2})-(january|february|march|april|may|june|july"
    r"|august|september|october|november|december)-(\d{4})$",
    re.IGNORECASE,
)


# A paper in a year folder the council has since moved under old/, e.g.
# /files/assets/public/v/1/council-meetings/2022/09.-20-july-2022/…
_MOVED_YEAR = re.compile(r"(/council-meetings/)(202[0-3])/")


def _moved(url: str) -> str:
    """The paper's working address: 2020–2023 folders now live under old/."""
    return _MOVED_YEAR.sub(r"\1old/\2/", url, count=1)


def folder_date(url: str):
    segments = unquote(urlparse(url).path).split("/")
    match = _FOLDER_DATE.match(segments[-2]) if len(segments) > 1 else None
    if not match:
        return None
    try:
        return parse_date(" ".join(match.groups())).date()
    except (ValueError, OverflowError):
        return None


def names_date(url: str, date) -> bool:
    """Whether the file's own name carries ``date``, as "9-december-2020" or
    "09-december-2020"."""
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1].lower()
    month = date.strftime("%B").lower()
    return any(
        f"{day}-{month}-{date.year}" in name for day in (date.day, f"{date.day:02d}")
    )


@register_scraper
class MidWesternScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 25 s for
    # 14 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    list_name = "Council Meetings - Agendas Listing"
    papers_by = "heading"
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "mid_western",
            "NSW",
            "https://www.midwestern.nsw.gov.au/Council/Council-meetings/Minutes-and-agendas",
        )

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        meeting = parse_date(row.date, dayfirst=True).date()
        papers = {}
        for kind, url in self.papers(content).items():
            filed = folder_date(url)
            if filed is not None and filed != meeting and not names_date(url, meeting):
                self.logger.warning(
                    f"{row.date} {row.meeting_type}: {kind} {url} is filed under "
                    f"{filed} and named for another date, so it is dropped"
                )
                continue
            papers[kind] = _moved(url)
        return papers
