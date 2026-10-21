import datetime
import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import (
    filename_of,
    filename_says_agenda_only,
    filename_says_minutes_only,
    find_date,
    find_month,
)
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://mingenew.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/shire-and-council/council-agendas-minutes/"

# Every agenda and minutes Mingenew has published since 2010 is one row of a
# server-rendered table on this page (DataTables only filters it in the
# browser): date added | title | category | download link. One request covers
# the whole history, which also keeps us well inside robots.txt's
# `Crawl-delay: 10`.
#
# Each row is one file, so a meeting is several rows: the agenda, the
# minutes, and their attachment booklets, audio recordings and item
# attachments ("18 February 2026 Ordinary Council Meeting Minutes – 11.1.2
# Belisama Project Plans"). Only the agenda and minutes are kept, and they
# are joined on the meeting's date and type.
#
# Titles are typed by hand and drift: "15 September 2026 Ordinary Council
# Meeting Agenda", "June 2022 Ordinary Council Meeting Agenda", "April 2022
# Ordinary Council Meeting Agenda – 20/04/2022", "15 March Special Council
# Meeting Agenda". The meeting date is read from the title first, then from
# the file name ("Ordinary-Council-Meeting-Agenda-15-June-2022-Public.pdf").
# The date-added column is when the file was uploaded, so it is used only to
# supply a year the title leaves out, never as a meeting date.

_TITLE_DATE_SLASHED = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2,4})(?!\d)")
_DAY_MONTH_NO_YEAR = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,10})\b")
# "(Confirmed 19 August 2026)" and "– Confirmed (19/10/2022)" date the
# confirming meeting, not this one, so they are cut before reading a date.
_CONFIRMATION = re.compile(r"\(?\b(?:un)?confirmed\b.*$", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
# A part of the meeting rather than its agenda or minutes. Matched against
# what follows a dash in the title ("… Minutes – Attachments Booklet") ...
_SUBDOCUMENT_TITLE = re.compile(
    r"attach|booklet|recording|audio|previous minutes|annual report|timeline"
    r"|^\s*\d+\.\d+",
    re.IGNORECASE,
)
# ... and against the file name, since "May 2021 Ordinary Council Meeting
# Agenda – 19/05/2021" links `Attachment-Booklet-…-19-May-2021-reduced.pdf`.
# "…-Agenda-and-Attachments.pdf" and "…-Minutes-with-Attachments-…" are the
# paper itself with its attachments bound in, so those are kept.
_SUBDOCUMENT_FILE = re.compile(
    r"(?<!with-)(?<!and-)attachment|booklet|recording|^annual-report|timetable",
    re.IGNORECASE,
)
# How far apart a lone agenda and lone minutes of one meeting type, in one
# month, can be dated and still be one meeting; see _join_moved.
_MOVED_DAYS = 7
_MONTH_WORDS = {
    name: number
    for number, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}


@dataclass
class _Row:
    kind: str  # "agenda" or "minutes"
    meeting: str
    url: str
    added: datetime.date
    confirmed: bool
    date: Optional[datetime.date]
    month: Optional[tuple[int, int]]


def _meeting_type(title: str) -> Optional[str]:
    lowered = title.lower()
    if "bush fire" in lowered or "bushfire" in lowered:
        # The volunteer brigades' AGM, not a meeting of the council.
        return None
    if "elector" in lowered:
        return "Annual Electors Meeting"
    if "audit" in lowered:
        return "Audit Committee"
    if "special" in lowered:
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


def _spaced(name: str) -> str:
    return re.sub(r"[-_]+", " ", name)


def _nearest_year(month: int, day: int, added: datetime.date) -> Optional[datetime.date]:
    """The date with that day and month closest to when the file went up.

    "15 March Special Council Meeting Agenda" was added on 13 March 2023, and
    "18 September Special Council Meeting Minutes" on 9 October 2024. An
    agenda goes up a week or two before the meeting and minutes a few weeks
    after it, so the nearest year is the meeting's.
    """
    candidates = []
    for year in (added.year - 1, added.year, added.year + 1):
        try:
            candidates.append(datetime.date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - added).days))


def _title_date(title: str, added: datetime.date) -> Optional[datetime.date]:
    found = find_date(title)
    if found:
        return found[0]
    match = _TITLE_DATE_SLASHED.search(title)
    if match:
        day, month, year = (int(g) for g in match.groups())
        if year < 100:
            year += 2000
        try:
            return datetime.date(year, month, day)
        except ValueError:
            pass
    match = _DAY_MONTH_NO_YEAR.match(title)
    if match:
        month = _MONTH_WORDS.get(match.group(2)[:3].lower())
        if month:
            return _nearest_year(month, int(match.group(1)), added)
    return None


@register_scraper
class MingenewScraper(BaseScraper):
    def __init__(self):
        super().__init__("mingenew", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _rows(self, soup) -> list[_Row]:
        table = soup.select_one("table.js-datable-public-documents")
        if table is None:
            raise ValueError(f"{self.council_name}: document table not found on {_LISTING_URL}")
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            link = tr.find("a", href=True)
            if len(cells) < 4 or not link:
                # The header row, and rows reading "No file available".
                continue
            url = link["href"].strip()
            filename = filename_of(url)
            if not filename.lower().endswith(".pdf"):
                continue
            title = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))
            category = cells[2].get_text(" ", strip=True).lower()
            try:
                added = datetime.datetime.strptime(cells[0].get_text(strip=True), "%Y%m%d").date()
            except ValueError:
                continue

            parts = re.split(r"\s+[–-]\s+", title)
            if any(_SUBDOCUMENT_TITLE.search(part) for part in parts[1:]):
                continue
            if _SUBDOCUMENT_FILE.search(filename):
                continue
            # Neither an agenda nor minutes: "February 2020 Annual Meeting of
            # Electors Annual Report 2018/19" links the annual report alone.
            if "annual report" in title.lower() and not re.search(
                r"agenda|minute", filename, re.IGNORECASE
            ):
                continue

            bare = _CONFIRMATION.sub("", title).strip()
            if re.search(r"\bminutes\b", bare, re.IGNORECASE):
                kind = "minutes"
            elif re.search(r"\bagenda\b", bare, re.IGNORECASE):
                kind = "agenda"
            else:
                kind = "minutes" if "minutes" in category else "agenda"
            # The listing now and then links the wrong file: the "16 August
            # 2023 … Minutes" row serves that meeting's agenda.
            if kind == "agenda" and filename_says_minutes_only(url):
                continue
            if kind == "minutes" and filename_says_agenda_only(url):
                continue

            # The file name as well as the title: "29 January 2025 Council
            # Meeting Minutes" is `Confirmed-Minutes-29-January-2025-Special-
            # Meeting.pdf`, the minutes of that day's special meeting.
            meeting = _meeting_type(f"{title} {_spaced(filename)}")
            if meeting is None:
                continue

            date = _title_date(bare, added)
            file_found = find_date(_spaced(filename))
            file_date = file_found[0] if file_found else None
            if date is None:
                date = file_date
            elif file_date and file_date != date:
                # "17 November 2021 … Minutes" links
                # `Minutes-Ordinary-Council-Meeting-13-October-2021.pdf`: a
                # file named for another meeting belongs to that meeting,
                # which has its own row.
                self.logger.info(
                    f"{self.council_name}: {title!r} links {filename}, dated "
                    f"{file_date}; not taken as the {date} {kind}"
                )
                continue
            month = None
            if date is None:
                month = find_month(bare) or find_month(_spaced(filename))
            rows.append(
                _Row(
                    kind=kind,
                    meeting=meeting,
                    url=url,
                    added=added,
                    confirmed=bool(_CONFIRMED.search(title)),
                    date=date,
                    month=month,
                )
            )
        return rows

    @staticmethod
    def _resolve_months(rows: list[_Row]) -> None:
        """Date a month-only file from its counterpart of the other kind.

        "February 2020 Annual Meeting of Electors Agenda" links
        `Agenda-for-Annual-Meeting-of-Electors-100220.pdf`, with no day the
        page spells out; its minutes are "2020 Electors' AGM Minutes –
        10/02/2020". Only resolved when exactly one meeting of that type
        falls in that month.
        """
        for row in rows:
            if row.date or not row.month:
                continue
            candidates = {
                other.date
                for other in rows
                if other.kind != row.kind
                and other.date
                and other.meeting == row.meeting
                and (other.date.year, other.date.month) == row.month
            }
            if len(candidates) == 1:
                row.date = candidates.pop()

    @staticmethod
    def _join_moved(meetings: dict[tuple, dict[str, _Row]]) -> None:
        """Join a lone agenda and lone minutes dated a few days apart.

        "October 2020 Council Meeting Agenda – 16/10/2020" and "October 2020
        Ordinary Council Meeting Minutes – 21/10/20" are one meeting: the
        agenda's title carries the day it was issued. Joined only when each
        is the other's sole candidate, on the minutes' date, because the
        minutes record when the meeting sat.
        """

        def lone(kind: str) -> list[tuple]:
            return [key for key, papers in meetings.items() if set(papers) == {kind}]

        for agenda_key in lone("agenda"):
            date, meeting = agenda_key

            def near(key) -> bool:
                return (
                    key[1] == meeting
                    and (key[0].year, key[0].month) == (date.year, date.month)
                    and abs((key[0] - date).days) <= _MOVED_DAYS
                )

            minutes_keys = [key for key in lone("minutes") if near(key)]
            rivals = [key for key in lone("agenda") if near(key)]
            if len(minutes_keys) == 1 and rivals == [agenda_key]:
                meetings[minutes_keys[0]]["agenda"] = meetings.pop(agenda_key)["agenda"]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the only request, and an empty result
        # would report a broken or blocked site as a council with no meetings.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        rows = self._rows(BeautifulSoup(html, "html.parser"))
        self._resolve_months(rows)

        meetings: dict[tuple, dict[str, _Row]] = {}
        for row in rows:
            if row.date is None:
                year = row.month[0] if row.month else row.added.year
                if year in wanted:
                    self.logger.warning(
                        f"{self.council_name}: cannot date {row.kind} {row.url}; skipped"
                    )
                continue
            if row.date.year not in wanted:
                continue
            papers = meetings.setdefault((row.date, row.meeting), {})
            current = papers.get(row.kind)
            # Confirmed minutes over unconfirmed; otherwise the newest upload,
            # which is how an amended agenda replaces the first issue.
            if current is None or (row.confirmed, row.added) > (current.confirmed, current.added):
                papers[row.kind] = row
        self._join_moved(meetings)

        results = []
        for (date, meeting), papers in sorted(meetings.items()):
            agenda_url = papers["agenda"].url if "agenda" in papers else None
            minutes_url = papers["minutes"].url if "minutes" in papers else None
            results.append(
                ScraperReturn(
                    name=meeting,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
