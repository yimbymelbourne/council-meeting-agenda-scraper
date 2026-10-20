"""Lithgow City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extra Ordinary
Council meetings back to 2018, and an Economic Development Committee until
2024; upcoming meetings appear once their agenda is up.

Papers are filed under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>`` (now and
then "Draft Minutes" or "Minutes - Draft"), with every link labelled
"Download PDF", so ``papers_by = "heading"``. The payload also carries each
agenda item's attachments in a Related Information list—including other
committees' draft minutes, adopted as items ("0811-Draft-Minutes-Ordinary-
Meeting-of-Council-…")—which heading mode never reads. 23 March 2026 has an
agenda and no minutes on the site.

**The listing's dates are not always the meeting's.** Lithgow files each
meeting's papers in a folder named for its date
(``/governance/meetings/2022/26-april-2022/``), and the payload opens with
the meeting's name and date ("Ordinary Meeting 26 April 2022"). Checked
against the PDFs' own front pages in October 2026:

* Three rows carry the wrong date, and the payload's title and the folder
  agree on the right one: 12 April 2022 is the 26 April 2022 meeting, 27
  August 2021 is 23 August 2021, and 27 November 2022—a Sunday—is 27
  November 2023. So where the title's date differs from the row's and the
  papers' folder names the title's date, the title's date is used. Neither
  source alone decides it: the 25 November 2024 meeting's title says 2025,
  and its folder ("25-novermber-2024", sic) does not back that up, so the
  row's date stands.
* The 6 April 2020 Extra Ordinary Meeting links the papers of the 9 March
  2020 confidential meeting: both the folder (``9-march-2020``) and the
  file names say 9 March. A paper whose folder and file name both name
  another date is not that meeting's, so it is dropped, and a meeting left
  with no papers is skipped. One source alone is not enough, as Mid-Western
  shows (`mid_western.py`): papers re-published into a later folder keep
  their own date in their name.

The Economic Development Committee is left out (``meeting_types``): it is an
advisory committee, not a Council or planning body, and each row kept costs
a payload request. Its six rows from 2020 also mostly lack minutes.

**The council filed 28 January 2025 under the 2026 year filter.** So every
2026 run logs a WARNING from the base class—"the 2026 filter returned
meetings from other years (['28 January 2025']); is list_name … still
right?"—and that warning is expected, not a renamed list, until the year
rolls over. A 2026 run drops the stray row (it is not a 2026 meeting), and
the unfiltered recording keeps it, but a one-year 2025 run never sees it: 11
meetings against 12 in the recorded history. Production asks only for the
current year, so only a one-year backfill of 2025 would miss it.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per meeting: 12 for 2026.
"""

import re
from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)

# The meeting's folder: "26-april-2022", or "9-march-2020-2" for a second
# meeting that day.
_FOLDER_DATE = re.compile(
    rf"^(\d{{1,2}})-({_MONTHS})-(\d{{4}})(?:-\d+)?$", re.IGNORECASE
)

# The payload's opening line: "Ordinary Meeting 26 April 2022".
_TITLE_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)


def _date(day: str, month: str, year: str):
    try:
        return parse_date(f"{day} {month} {year}").date()
    except (ValueError, OverflowError):
        return None


def folder_date(url: str):
    """The date the paper's folder is named for, or None if it is not named
    for one (or misspelt, as "25-novermber-2024" is)."""
    segments = unquote(urlparse(url).path).split("/")
    if len(segments) < 2:
        return None
    match = _FOLDER_DATE.match(segments[-2])
    return _date(*match.groups()) if match else None


def title_date(content: BeautifulSoup):
    title = content.find("p")
    match = _TITLE_DATE.search(title.get_text(" ", strip=True)) if title else None
    return _date(*match.groups()) if match else None


def names_date(url: str, date) -> bool:
    """Whether the file's own name carries ``date``, as "9-december-2020" or
    "09-december-2020"."""
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1].lower()
    month = date.strftime("%B").lower()
    return any(
        f"{day}-{month}-{date.year}" in name for day in (date.day, f"{date.day:02d}")
    )


@register_scraper
class LithgowScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 23 s for
    # 12 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 23

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # "Ordinary Meeting" and "Extra Ordinary Meeting".
    meeting_types = re.compile(r"\bordinary\b", re.IGNORECASE)
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "lithgow",
            "NSW",
            "https://www.lithgow.nsw.gov.au/Governance/Council-Meetings/Minutes-and-Agendas",
        )

    def _meeting_date(self, content: BeautifulSoup, row: ListingRow):
        listed = parse_date(row.date, dayfirst=True).date()
        titled = title_date(content)
        if titled is None or titled == listed:
            return listed
        folders = {folder_date(url) for url in self.papers(content).values() if url}
        if titled in folders:
            self.logger.info(
                f"{row.date} {row.meeting_type}: the payload and the papers' "
                f"folder both say {titled}, so that date is used"
            )
            return titled
        return listed

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        meeting = self._meeting_date(content, row)
        papers = {}
        for kind, url in self.papers(content).items():
            filed = folder_date(url)
            if filed is not None and filed != meeting and not names_date(url, meeting):
                self.logger.warning(
                    f"{row.date} {row.meeting_type}: {kind} {url} is filed under "
                    f"{filed} and named for another date, so it is dropped"
                )
                continue
            papers[kind] = url
        return papers

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> Optional[ScraperReturn]:
        record = super().build_return(content, row)
        if record is None:
            return None
        meeting = self._meeting_date(content, row)
        if meeting != parse_date(row.date, dayfirst=True).date():
            # The listing's own format, so a corrected date reads like the rest.
            record.date = meeting.strftime("%d %B %Y")
        return record
