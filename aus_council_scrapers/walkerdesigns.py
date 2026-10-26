"""Council meeting papers on sites built by Walker Designs.

Walker Designs, a Launceston agency, builds several northern Tasmanian
council sites on Craft CMS (`/cpresources/` in robots.txt, `/volumes/` asset
paths, "Website by Walker Designs" in the footer). Its council-meetings
template puts the whole history on one static page: one `<table>` per year,
a header row naming the columns, and one row per meeting:

    Date | Meeting | Agenda | [Attachments] | Minutes | Video/Audio | [Youtube]

The document cells hold only icons. What a link is says nothing in the link
text; it is the column it sits in, with the file's name in a `title`
tooltip. Meander Valley, Northern Midlands and George Town use it, with or
without the Attachments and Youtube columns, so the columns are read from
each table's own header rather than by position. A table with no header row
is not a meeting table: Northern Midlands puts its "2026 Ordinary Council
Meeting Dates" schedule above the meetings as one.

The same agency built Dorset's site on a different template (cards, not a
table), which `DorsetScraper` reads by overriding `listing_rows`. What
follows applies to rows from either.

The column is the main evidence for what a document is, because the file
names are often opaque ("2023-07-11_Ordinary_Meeting_-__XAfCpYlG80iHi4lqVMhlzg_v2.pdf").
But the councils misfile now and then, so each row is checked:

- **A document filed in the wrong column.** A link in the Agenda column
  whose title or file name says minutes, and neither says agenda, is
  the minutes (Meander Valley's 10 October 2023 minutes sit in the Agenda
  column, with the Minutes column empty), and the same the other way round.
  Where the title and the file name disagree, the column stands: Meander
  Valley's December 2021 minutes are titled "Ordinary Council Meeting
  Agenda" but named `ORDINARY-Minutes-December-2021.pdf`, and are minutes.
- **Things that are not the paper.** Non-PDF links (Meander Valley's 8 March
  2022 Agenda cell holds only the audio recording), single agenda items
  ("Agenda Item 9.2 Stormwater Drainage Plan"), annual reports and late or
  supplementary items are left out.
- **Several agendas.** An agenda split into parts is stored as part 1 (or
  the part starting at page 1, as Meander Valley splits by page range). An
  amended or updated agenda beats the original. A document titled as the
  agenda's attachments is used only when nothing else is in the column:
  Meander Valley's 14 May 2024 "Ordinary Council Agenda Attachments" and
  Northern Midlands' 15 March 2021 "AGM Agenda Attachments" are both the
  agenda itself (checked against the PDFs).
- **A row with the wrong date.** The row's date is one witness; the agenda,
  the minutes and the recording each name a date in their title or file
  name, and are one witness each. The row's date stands unless at least two
  documents agree on another date and none names the row's. George Town's
  2023 AGM row says 28 November (the ordinary meeting's date) while its
  agenda and minutes both say 16 November; Meander Valley's November 2022
  row says the 9th, a Wednesday, while all three documents say Tuesday the
  8th. A single dissenting document is a typo in the document (Meander
  Valley's 10 September 2024 agenda says 2025).

Rows with no documents are upcoming meetings whose papers are not out yet,
and are left out. The listing publishes no start times outside the PDFs.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        1,
    )
    for name in names
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "20 January 2026", "Friday 15 January 2021", "21 Sept 2026", "9th June 2026".
_DAY_MONTH_YEAR = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})\.?,?\s+(20\d\d)(?!\d)",
    re.IGNORECASE,
)
# "Jan 20, 2026", Meander Valley's row dates.
_MONTH_DAY_YEAR = re.compile(
    rf"(?<![a-z])({_MONTH_PATTERN})\.?\s+(\d{{1,2}}),?\s+(20\d\d)(?!\d)",
    re.IGNORECASE,
)
# "2026 10 19 Open Council Agenda", Northern Midlands' and George Town's
# titles, which lead with the date year first.
_YEAR_MONTH_DAY = re.compile(r"(?<!\d)(20\d\d)\s(\d\d)\s(\d\d)(?!\d)")
# "Dorset-Council-Meeting-Minutes-19-08-2024", "Recording 12 05 2020".
_DAY_MONTH_NUMERIC_YEAR = re.compile(r"(?<!\d)(\d{1,2})\s(\d{1,2})\s(20\d\d)(?!\d)")


def _date(year: str, month: int, day: str) -> Optional[datetime.date]:
    try:
        return datetime.date(int(year), month, int(day))
    except ValueError:
        return None


def find_date(text: str) -> Optional[datetime.date]:
    """The first full date written in `text`, or None.

    Month-only dates ("February 2021 Ordinary Council Meeting Agenda") are
    not dates here: they cannot vote on the day.
    """
    # Underscores and hyphens are word separators in file names.
    text = re.sub(r"[_\-.]+", " ", text)
    found = []
    for pattern, order in (
        (_DAY_MONTH_YEAR, "dmy"),
        (_MONTH_DAY_YEAR, "mdy"),
        (_YEAR_MONTH_DAY, "ymd"),
        (_DAY_MONTH_NUMERIC_YEAR, "dmy#"),
    ):
        for m in pattern.finditer(text):
            if order == "dmy":
                date = _date(m.group(3), _MONTHS[m.group(2).lower()], m.group(1))
            elif order == "mdy":
                date = _date(m.group(3), _MONTHS[m.group(1).lower()], m.group(2))
            elif order == "ymd":
                date = _date(m.group(1), int(m.group(2)), m.group(3))
            else:
                date = _date(m.group(3), int(m.group(2)), m.group(1))
            if date is not None:
                found.append((m.start(), date))
                break
    return min(found)[1] if found else None


# Anything in an Agenda or Minutes cell that is not the paper itself: a
# single item's report, the annual report tabled at an AGM, a late or
# supplementary item, or a recording.
_NOT_THE_PAPER = re.compile(
    r"\bitems?\b|annual\s+report|supplementary|\blate\b|audio|recording",
    re.IGNORECASE,
)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minute", re.IGNORECASE)
# "Agenda Attachments" but not "Agenda and Attachments" or
# "Agenda with attachments", which are the agenda.
_ATTACHMENTS_ONLY = re.compile(
    r"(?<!and\s)(?<!with\s)\battachments?\b", re.IGNORECASE
)
_SUPERSEDES = re.compile(r"\bamended\b|\bupdated?\b|\brevised\b", re.IGNORECASE)
_PROVISIONAL = re.compile(r"unconfirmed|draft", re.IGNORECASE)
# "Part 2", "_Part3", and Meander Valley's page ranges "244 to 349".
_PART = re.compile(r"\bpart\s*(\d+)\b|\b(\d+)\s+to\s+\d+\b", re.IGNORECASE)


@dataclass
class WalkerDesignsDocument:
    url: str
    # The tooltip or card title, which names the document in words.
    title: str

    @property
    def filename(self) -> str:
        return unquote(urlparse(self.url).path.rsplit("/", 1)[-1])

    @property
    def text(self) -> str:
        return f"{self.title} {self.filename}"

    @property
    def is_pdf(self) -> bool:
        return self.filename.lower().endswith(".pdf")

    @property
    def own_date(self) -> Optional[datetime.date]:
        return find_date(self.title) or find_date(self.filename.rsplit(".", 1)[0])


@dataclass
class WalkerDesignsRow:
    """One meeting as the listing presents it, before any checking."""

    date: datetime.date
    name: str
    webpage_url: str
    agendas: list[WalkerDesignsDocument] = field(default_factory=list)
    minutes: list[WalkerDesignsDocument] = field(default_factory=list)
    # Other dated documents in the row (recordings, attachments). They are
    # never stored, only consulted on the date.
    others: list[WalkerDesignsDocument] = field(default_factory=list)


def _says(doc: WalkerDesignsDocument, pattern: re.Pattern) -> bool:
    return bool(pattern.search(doc.title) or pattern.search(doc.filename))


def _rank(doc: WalkerDesignsDocument, position: int) -> tuple:
    part = _PART.search(doc.text.replace("_", " ").replace("-", " "))
    part_number = int(part.group(1) or part.group(2)) if part else 0
    return (
        bool(_ATTACHMENTS_ONLY.search(doc.title)),
        bool(_PROVISIONAL.search(doc.title)),
        not _SUPERSEDES.search(doc.text),
        part_number,
        position,
    )


def _pick(docs: list[WalkerDesignsDocument]) -> Optional[str]:
    if not docs:
        return None
    return min(enumerate(docs), key=lambda pair: _rank(pair[1], pair[0]))[1].url


class WalkerDesignsMeetingsScraper(BaseScraper):
    """Reads a Walker Designs council-meetings page of per-year tables.

    A subclass supplies `listing_url`, the page holding the tables. One
    request covers every year, so `years_filter` only decides which rows are
    kept.
    """

    listing_url: str
    # Used when a row's Meeting cell is empty.
    fallback_name = "Council Meeting"
    # The council's older labels for a meeting type, mapped to the one it
    # uses now, so one type keeps one name across years. Meander Valley's
    # ordinary meetings are "Council Meeting" until 2025 and "Ordinary
    # Meeting" from 2026.
    meeting_names: dict[str, str] = {}
    # The first year the council lists. Later than EARLIEST_YEAR where the
    # listing starts later (George Town and Dorset start in 2021), so a full
    # run does not warn about years that were never published.
    earliest_year: int = EARLIEST_YEAR

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        years = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        return {y for y in years if y >= self.earliest_year}

    # --- reading the listing -------------------------------------------

    def listing_rows(self, wanted: set[int]) -> list[WalkerDesignsRow]:
        """Every meeting row on the listing. Overridden for Dorset's cards."""
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(self.listing_url), "html.parser"
        )
        rows: list[WalkerDesignsRow] = []
        meeting_tables = 0
        for table in soup.find_all("table"):
            header = table.find("tr")
            if header is None or not header.find("th"):
                # A schedule of dates, not a table of meetings.
                continue
            columns = [
                " ".join(cell.get_text(" ", strip=True).split()).lower()
                for cell in header.find_all(["th", "td"])
            ]
            if "date" not in columns or not {"agenda", "minutes"} & set(columns):
                continue
            meeting_tables += 1
            for tr in table.find_all("tr"):
                if tr is header or tr.find("th"):
                    continue
                if row := self._table_row(columns, tr.find_all("td")):
                    rows.append(row)
        if not meeting_tables:
            # Every Walker Designs meetings page has these tables. None means
            # the template changed or something else answered (a challenge
            # page), and returning nothing would read as a council with no
            # meetings.
            raise ValueError(
                f"{self.council_name}: no meeting tables on {self.listing_url}"
            )
        return rows

    def _table_row(self, columns: list[str], cells) -> Optional[WalkerDesignsRow]:
        by_column = dict(zip(columns, cells))
        date_cell = by_column.get("date")
        if date_cell is None:
            return None
        date_text = " ".join(date_cell.get_text(" ", strip=True).split())
        date = find_date(date_text)
        if date is None:
            if date_text:
                self.logger.warning(
                    f"{self.council_name}: unreadable meeting date {date_text!r}; "
                    f"row left out"
                )
            return None
        name_cell = by_column.get("meeting")
        name = (
            " ".join(name_cell.get_text(" ", strip=True).split()) if name_cell else ""
        )
        name = name or self.fallback_name
        row = WalkerDesignsRow(
            date=date,
            name=self.meeting_names.get(name, name),
            webpage_url=self.listing_url,
        )
        for column, cell in by_column.items():
            docs = [
                WalkerDesignsDocument(
                    url=link["href"].strip(),
                    title=" ".join(
                        (link.get("title") or link.get_text(" ", strip=True)).split()
                    ),
                )
                for link in cell.find_all("a", href=True)
                if link["href"].strip().startswith("http")
            ]
            if column == "agenda":
                row.agendas.extend(docs)
            elif column == "minutes":
                row.minutes.extend(docs)
            elif column not in ("date", "meeting"):
                row.others.extend(docs)
        return row

    # --- checking a row -------------------------------------------------

    def _sort_documents(self, row: WalkerDesignsRow) -> None:
        """Drop what is not the paper and move what is in the wrong column."""
        agendas, minutes = [], []
        for column, docs in (("agenda", row.agendas), ("minutes", row.minutes)):
            for doc in docs:
                if not doc.is_pdf or _NOT_THE_PAPER.search(doc.title):
                    if doc.is_pdf:
                        row.others.append(doc)
                    continue
                says_agenda = _says(doc, _AGENDA)
                says_minutes = _says(doc, _MINUTES)
                if column == "agenda" and says_minutes and not says_agenda:
                    self.logger.info(
                        f"{self.council_name}: {doc.title!r} is in the {row.date} "
                        f"Agenda column but is the minutes"
                    )
                    minutes.append(doc)
                elif column == "minutes" and says_agenda and not says_minutes:
                    self.logger.info(
                        f"{self.council_name}: {doc.title!r} is in the {row.date} "
                        f"Minutes column but is the agenda"
                    )
                    agendas.append(doc)
                else:
                    (agendas if column == "agenda" else minutes).append(doc)
        row.agendas, row.minutes = agendas, minutes

    def _reconcile_date(self, row: WalkerDesignsRow) -> datetime.date:
        votes: list[datetime.date] = []
        for docs in (row.agendas, row.minutes, row.others):
            # One vote per column, from its first dated document: a
            # four-part agenda is one witness, not four.
            date = next((d for doc in docs if (d := doc.own_date)), None)
            if date is not None:
                votes.append(date)
        if not votes or row.date in votes:
            return row.date
        best = max(set(votes), key=votes.count)
        return best if votes.count(best) >= 2 else row.date

    # --- entry point ----------------------------------------------------

    def _check_years_have_meetings(self, wanted, meetings, years_listed) -> None:
        """Fail a wanted year that has begun and come back with no papers.

        Each of these councils meets monthly and puts the agenda up before
        the meeting, so a year that is under way with nothing in it means
        the newest table (or Dorset's newest year page) has changed shape,
        or never got read, not that the council stopped meeting. Raising
        makes production report the council as failed rather than as fine
        with 0 meetings. The first 90 days of a year only warn: the new
        year's table goes up with the first meeting, and January is often
        a recess (as in craft.py, which uses the same window).
        """
        today = clock.today()
        with_papers = {row.date.year for row in meetings}
        for year in sorted(wanted):
            if year > today.year or year in with_papers:
                continue
            message = f"{self.council_name}: no meetings with papers for {year}"
            if year not in years_listed:
                message += " (the listing has no rows for that year)"
            if today - datetime.date(year, 1, 1) > datetime.timedelta(days=90):
                raise RuntimeError(
                    message + "; the listing markup has probably changed"
                )
            self.logger.warning(message)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        if not wanted:
            self.logger.info(
                f"{self.council_name}: the listing starts in {self.earliest_year}; "
                f"no years to read"
            )
            return []

        meetings: dict[tuple[str, datetime.date], WalkerDesignsRow] = {}
        years_listed: set[int] = set()
        for row in self.listing_rows(wanted):
            years_listed.add(row.date.year)
            self._sort_documents(row)
            if not row.agendas and not row.minutes:
                # An upcoming meeting, or one whose papers were never put up.
                continue
            date = self._reconcile_date(row)
            if date.year not in wanted:
                continue
            if date != row.date:
                # Logged only for a wanted year, so a production run does not
                # repeat old corrections every night.
                self.logger.warning(
                    f"{self.council_name}: {row.name} row dated {row.date}, but "
                    f"its documents name {date}; taken as {date}"
                )
            key = (row.name, date)
            merged = meetings.get(key)
            if merged is None:
                row.date = date
                meetings[key] = row
                continue
            # The same meeting listed twice (Dorset lists agendas and minutes
            # on separate pages): one record with both papers, pointing at
            # the page the agenda is on.
            if row.agendas and not merged.agendas:
                merged.webpage_url = row.webpage_url
            merged.agendas.extend(row.agendas)
            merged.minutes.extend(row.minutes)

        self._check_years_have_meetings(wanted, meetings.values(), years_listed)

        results = []
        for row in sorted(meetings.values(), key=lambda r: (r.date, r.name)):
            agenda_url = _pick(row.agendas)
            minutes_url = _pick(row.minutes)
            results.append(
                ScraperReturn(
                    name=row.name,
                    date=row.date.isoformat(),
                    time=None,
                    webpage_url=row.webpage_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
