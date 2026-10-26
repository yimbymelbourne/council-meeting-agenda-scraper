"""Councils that file their papers in CouncilConnect's document library.

Some councils on CouncilConnect (see councilconnect.py) never used its
meetings module, or left its meeting pages empty, and publish agendas and
minutes only in the site's document library instead:

    /documents/                      the library's index
    /documents/?CategoryId=<id>      one folder (301 to its own slug)
    /documents/<id>/<slug>           one document, served as the PDF itself

The index carries a `select.categories-dropdown` with one option
per folder, labelled with the folder's path ("Council Meeting Agendas >
2026", "2025 - Minutes", "Minutes & Agendas 2026"). The folder slugs are
irregular from year to year (Northampton's 2023 agendas are `agenda-2023`
beside `agendas-2024`), and next year's folder does not exist until its
first paper is filed, so folders are found by their label in the index
rather than built from a pattern: the index is one request, and each year
costs its agenda and minutes folders on top. A folder lists every document
in it on one page; none of the nine councils' folders has a pager, the
biggest holding 255 documents.

A document's label is all there is to go on, typed by hand:

    01 - Agenda - Ordinary Council Meeting - 24 February 2026 (20/02/2026)
    Minutes - 26-11-2025 (Confirmed) (28/11/2025)
    21 February 2020 (14/02/2020)
    Agenda OCM February 2025 (25/02/2025)

The bracketed date at the end (`span.table-date`) is a "document date" the
council types when it uploads the file. It is not the meeting date—Yilgarn's
September 2026 agenda says 11/09 and its minutes 24/09, and Boyup Brook's
January 2025 attachments are dated a year early—so it is never read as one.

Whether a document is the agenda or the minutes comes from its label and,
where the label says neither ("21 February 2020"), from the folder it is
filed in. The label wins over the folder: Yalgoo files a Paynes Find agenda
in its minutes folder. Attachments, recordings, late items and briefing
papers are filed beside the papers and are never read as them.

**Which meetings.** Council meetings (ordinary and special), electors'
meetings and development assessment panels. Audit and other committees are
left out where they share a folder with the Council's papers (Murchison,
Yilgarn, Boyup Brook) and their own folders are not read, so a council comes
out the same whichever way it happens to file them.

**Month-only labels.** Murchison, Yilgarn and Cuballing label many
documents with a month and no day ("Agenda OCM February 2025"). A day is
never invented for them. Such a document joins a meeting only when the
council itself names that meeting's day somewhere it is read:

- another paper of the same meeting type in the same month carries a full
  date (Cuballing's agendas are month-only and its 2026 minutes dated);
- the council's published meeting schedule for the year (`schedule_path`)
  gives the one ordinary meeting in that month;
- a subclass's `corrections` give it, from the paper's own cover;
- with `pdf_dates` set, the paper's own first page gives a day in the
  label's month (see pdf_dates.py), read only for the years being scraped.

Otherwise it is left out, and logged so a run says what was dropped.
Recordings are not used, though their labels often carry the day: of
fifteen checked against agenda covers at Murchison and Cuballing, two
were wrong ("OCM Recording 29 May 2025" for a meeting on 22 May, its
minutes posted on the 27th).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.councilconnect import ELECTORS_NAMES
from aus_council_scrapers.pdf_dates import PDF_FULL_LIMIT, meeting_date_from_pdf

AGENDA = "agenda"
MINUTES = "minutes"

# A document's own address. The id is the library's, the slug its label
# slugified; the page serves the PDF itself (application/pdf, no redirect).
_DOCUMENT_PATH = re.compile(r"^/documents/(?P<id>\d+)/[^/]+/?$")

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?"

# "24 February 2026", "15  September 2020", "24th October 2025", "21 July"
# (Northampton, year from the folder), "17 November2022" (Boyup Brook). A
# month is ended by anything but a letter, so the last still reads.
_DAY_MONTH = re.compile(
    rf"(?<![\d.])(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?(?P<month>{_MONTH})(?![a-z])"
    r",?(?:\s*(?P<year>(?:19|20)\d{2})\b)?",
    re.IGNORECASE,
)
# "December 16 2020" (Cuballing's 2020 electors' minutes).
_MONTH_DAY = re.compile(
    rf"\b(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>(?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)
# "26-11-2025", "28-4-2020", "9-9-2026" (Narrogin); "28.02.2025" (Murchison's
# recordings).
_NUMERIC = re.compile(
    r"(?<![\d.])(?P<day>\d{1,2})[-/.](?P<month>\d{1,2})[-/.](?P<year>(?:19|20)\d{2})(?![\d.])"
)
_MONTH_ONLY = re.compile(rf"\b(?P<month>{_MONTH})(?![a-z])", re.IGNORECASE)
_YEAR = re.compile(r"(?<![\d/])(?:19|20)\d{2}(?![\d/])")
# Yalgoo's leading sequence number, "2020-07 Ordinary Council Meeting Agenda".
_NUMBERED = re.compile(r"^\s*((?:19|20)\d{2})-(\d{2})\b")

# Not the meeting's agenda or minutes, whatever else the label says. Matched
# with any "and attachments" packet wording taken out first (see _PACKET), so
# "Agenda and Attachments - 27 May 2021" (Boyup Brook's only agenda for that
# meeting) is still read. "Attach" also catches Yilgarn's "Attachemnts" and
# Murchison's "Attachements". "Notice - Failed Audio" is Kojonup's note in
# place of a recording.
_NOT_THE_PAPER = re.compile(
    r"attach|appendi|record|audio|voice|\bvideo\b|addend|\blate\b|supplement"
    r"|presentation|\bnotice\b|briefing|\bforum\b|workshop|confidential"
    r"|\btabled\b|\bschedule\b|\bdates\b",
    re.IGNORECASE,
)
# A packet that bundles its attachments, as opposed to being one.
_PACKET = re.compile(
    r"(?:\b(?:with|and|incl\w*)|&)\s+(?:all\s+)?attach\w*", re.IGNORECASE
)
_COMBINED = re.compile(r"\bcombined\b", re.IGNORECASE)
# Bodies left out (see the module docstring). "Commitee" is Murchison's.
# "Tender" alone is not one: Boyup Brook's "Special Council Agenda - 2 March
# 2023 - Tender 23/001" is a Council meeting called to award a tender, and a
# tender committee is caught by "committee".
_OTHER_BODIES = re.compile(
    r"audit|committee|commitee|\blemc\b|emergency\s+management",
    re.IGNORECASE,
)

_AGENDA_WORD = re.compile(r"agend", re.IGNORECASE)
_MINUTES_WORD = re.compile(r"minute|\bmins\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"un-?confirm", re.IGNORECASE)
_CONFIRMED = re.compile(r"confirm", re.IGNORECASE)
_SUMMARY = re.compile(r"\bsummary\b", re.IGNORECASE)
_AMENDED = re.compile(r"amended|revised|updated", re.IGNORECASE)

# A parenthetical note to readers, not part of the document's name: Cuballing's
# "Minutes - April 2025 (Please be aware there is no audio recording
# available for this meeting", unclosed. Left in, "audio recording" would
# throw its only minutes away.
_READER_NOTE = re.compile(r"\((?:please|note)\b[^)]*\)?", re.IGNORECASE)

# "Ordinary" as typed: Kojonup's "Oridnary", Yalgoo's "Ordianry".
_ORDINARY = r"\bor[a-z]{4}ry\b"

# Meeting types, matched against the label with its dates taken out. The
# first match names the meeting. A label naming none of them is still an
# ordinary meeting when every word left is one of _FILLER ("Minutes -
# 26-11-2025", "02 - Agenda 18 February 2020", "SoKO Ordinary Meeting"),
# and otherwise is some other paper and is not read.
DEFAULT_NAMES: tuple[tuple[re.Pattern, str], ...] = (
    *ELECTORS_NAMES,
    (
        re.compile(r"\bagm\b|annual\s+general\s+meeting", re.IGNORECASE),
        "Annual Meeting of Electors",
    ),
    (
        re.compile(r"regional\s+development\s+assessment\s+panel", re.IGNORECASE),
        "Regional Development Assessment Panel",
    ),
    (
        re.compile(r"development\s+assessment\s+panel|\bj?dap\b", re.IGNORECASE),
        "Development Assessment Panel",
    ),
    (re.compile(r"special|\bscm\b", re.IGNORECASE), "Special Council Meeting"),
    (re.compile(rf"{_ORDINARY}|\bocm\b", re.IGNORECASE), "Ordinary Council Meeting"),
)

# Words that say nothing about which meeting a paper is for: the kind of
# document, its status, the council's own name or initials, and the "to be
# held on" of Boyup Brook's longer labels.
_FILLER = frozenset(
    """
    a agenda agendas minute minutes mins and the of for on to be being held
    council meeting meetings shire public part confirmed unconfirmed
    combined final draft copy version summary
    """.split()
)

# The reports an agenda or minutes carries, named after it: Yalgoo's "Agenda
# & Reports", Yilgarn's "Agenda - December 2021 - Report". A bare "Reports"
# is something else: Yalgoo's "2024-01 Ordinary Council Meeting Reports" is
# the month's financial statements, filed among the agendas.
_WITH_REPORTS = re.compile(
    r"(?:&|\band\b|[-–])\s*(?:financial\s+)?reports?\b", re.IGNORECASE
)


@dataclass
class _Document:
    kind: str
    name: str
    url: str
    label: str
    folder_url: str
    rank: int
    doc_id: int
    date: Optional[datetime.date] = None
    month: Optional[tuple[int, int]] = None  # (year, month) when no day is given
    # False where the label names no meeting type and the name is the
    # council's usual meeting by default ("Minutes - 2 April 2020").
    typed: bool = True
    # Set only by a correction, to tell apart two meetings of one type on
    # one day (see _meetings).
    time: Optional[str] = None
    # The month a numbered label's sequence names ("2020-07 Ordinary Council
    # Meeting Agenda"), used only to bound a date read from the PDF
    # (`numbered_months`).
    pdf_month: Optional[tuple[int, int]] = None


@dataclass
class _Folder:
    category_id: str
    label: str
    year: Optional[int]
    kind: Optional[str]  # AGENDA, MINUTES, or None where it holds both


class CouncilConnectDocumentLibraryScraper(BaseScraper):
    """Base class for councils whose papers live in the document library.

    A subclass supplies the site origin and, as its library needs:

    `folder_pattern` / `skip_folder_pattern`
        Folder labels read, and folders left out of those. A folder is read
        when its label matches the first and not the second and names one
        year, and that year is wanted.
    `undated_folders`
        Exact labels of folders with no year that hold papers ("Annual
        Electors Meeting"), read on every run whatever the year asked for.
    `names`
        `((pattern, name), ...)` meeting types; see DEFAULT_NAMES.
    `name_noise`
        Words to take out of a label before its name is judged: Yalgoo's
        "Paynes Find", where some meetings are held.
    `extra_name_words`
        Words that, like "special" or "electors", may make up a label that
        is only a meeting's name, for a council with a meeting type of its
        own (Northampton's "1 August 2025 - Budget").
    `schedule_path`
        The council's page of meeting dates for the current year, read only
        when a month-only ordinary meeting's day is otherwise unknown.
    `corrections`
        `{document url: {"date": ISO date, "name": ..., "kind": ...,
        "time": "3:30 PM"}}` for documents whose label is wrong or says too
        little, each checked by reading the document. Applied before the
        papers are grouped into meetings. A time is given only where two
        meetings of one type share a day, and then to every paper of both.
    `wrong_documents`
        `{document url: why}`: documents that are not the paper their label
        says, by their contents. Never emitted.
    `first_year`
        Folders before it are not read.
    `numbered_months`
        For a council that numbers its papers "<year>-<month>" and gives no
        month otherwise (Yalgoo's "2020-07 Ordinary Council Meeting
        Agenda"): with `pdf_dates`, such a paper is dated from its PDF, and
        only a day in that month is taken. The number is a sequence, not
        always the meeting's month (Yalgoo's "2025-02" papers are for a
        meeting held on 7 March), so it is never used for anything else,
        and a paper whose meeting fell in another month is left out.
    `pdf_dates` / `pdf_kinds` / `pdf_full_limit`
        Date a month-only paper that nothing above dates from its PDF's
        first page, reading the meeting's papers in `pdf_kinds` order and
        stopping at the first that gives a day in the label's month. Each
        meeting so dated costs one or two requests a night, so it is off by
        default; `pdf_full_limit` bounds a file read whole.
    """

    folder_pattern: re.Pattern = re.compile(r"agend|minut", re.IGNORECASE)
    skip_folder_pattern: re.Pattern = re.compile(
        r"attach|committee|commitee|record|audio|lemc", re.IGNORECASE
    )
    undated_folders: tuple[str, ...] = ()
    names: tuple[tuple[re.Pattern, str], ...] = DEFAULT_NAMES
    name_noise: Optional[re.Pattern] = None
    extra_name_words: frozenset[str] = frozenset()
    schedule_path: Optional[str] = None
    corrections: dict[str, dict[str, str]] = {}
    wrong_documents: dict[str, str] = {}
    first_year: int = EARLIEST_YEAR
    ordinary_name: str = "Ordinary Council Meeting"
    pdf_dates: bool = False
    numbered_months: bool = False
    pdf_kinds: tuple[str, ...] = (AGENDA, MINUTES)
    pdf_full_limit: int = PDF_FULL_LIMIT

    # --- years -------------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    # --- folders -----------------------------------------------------------

    def _folders(self, index_html: str, wanted: set[int]) -> list[_Folder]:
        soup = BeautifulSoup(index_html, "html.parser")
        options = soup.select("select.categories-dropdown option")
        if not options:
            raise RuntimeError(
                f"{self.council_name}: no folder list on {self.base_url}/documents/; "
                "the document library may have changed"
            )
        folders = []
        for option in options:
            category_id = (option.get("value") or "").strip()
            label = re.sub(r"\s+", " ", option.get_text(" ", strip=True))
            if not category_id or category_id == "0":
                continue
            kind = self._folder_kind(label)
            if label in self.undated_folders:
                folders.append(_Folder(category_id, label, None, kind))
                continue
            if not self.folder_pattern.search(label) or self.skip_folder_pattern.search(
                label
            ):
                continue
            years = {int(y) for y in _YEAR.findall(label)}
            if len(years) != 1:
                continue
            year = years.pop()
            if year < self.first_year or year not in wanted:
                continue
            folders.append(_Folder(category_id, label, year, kind))
        return folders

    @staticmethod
    def _folder_kind(label: str) -> Optional[str]:
        agenda = bool(_AGENDA_WORD.search(label))
        minutes = bool(_MINUTES_WORD.search(label))
        if agenda and not minutes:
            return AGENDA
        if minutes and not agenda:
            return MINUTES
        return None

    def _folder_url(self, folder: _Folder) -> str:
        return f"{self.base_url}/documents/?CategoryId={folder.category_id}"

    def _folder_items(self, html: str, page_url: str):
        """(label, css class, url, id) for each document listed in a folder.

        Two layouts: a table (`td.table-title`, the anchor classed by file
        type—`doc-pdf`, `doc-audio`, `doc-movie`, `doc-link`) and a list
        (`div.item-text`, unclassed). Kojonup uses both, a year apiece.
        """
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find(class_="documentcentre-items")
        if container is None:
            raise RuntimeError(
                f"{self.council_name}: no document list on {page_url}; "
                "the document library may have changed"
            )
        items = []
        for link in container.find_all("a", href=True):
            url = urljoin(page_url, link["href"])
            match = _DOCUMENT_PATH.match(urlparse(url).path)
            if not match:
                continue
            stamp = link.find(class_="table-date")
            if stamp:
                stamp.extract()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if not label:
                label = re.sub(r"^View\s*-\s*", "", link.get("title") or "")
            css = " ".join(link.get("class") or [])
            items.append((label, css, url.rstrip("/"), int(match.group("id"))))
        return items

    # --- labels ------------------------------------------------------------

    def _read_date(self, text: str, folder_year: Optional[int]):
        """(date, (year, month)) from a label: a full date, or failing that a
        month, or neither. A day and month with no year take the folder's."""
        for pattern in (_DAY_MONTH, _MONTH_DAY):
            for match in pattern.finditer(text):
                year = match.group("year")
                year = int(year) if year else folder_year
                if year is None:
                    continue
                month = _MONTHS[match.group("month")[:3].lower()]
                try:
                    return datetime.date(year, month, int(match.group("day"))), None
                except ValueError:
                    continue
        for match in _NUMERIC.finditer(text):
            try:
                return (
                    datetime.date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    ),
                    None,
                )
            except ValueError:
                continue
        month = _MONTH_ONLY.search(text)
        if month:
            years = [int(y) for y in _YEAR.findall(text)]
            year = years[0] if len(set(years)) == 1 else folder_year
            if year is not None:
                return None, (year, _MONTHS[month.group("month")[:3].lower()])
        return None, None

    def _residual_words(self, text: str) -> set[str]:
        """The words of a label that are left once its dates, numbering,
        weekdays and packet wording are gone."""
        text = _DAY_MONTH.sub(" ", text)
        text = _MONTH_DAY.sub(" ", text)
        text = _NUMERIC.sub(" ", text)
        text = _MONTH_ONLY.sub(" ", text)
        text = re.sub(rf"\b{_WEEKDAY}", " ", text, flags=re.IGNORECASE)
        text = _PACKET.sub(" ", text)
        text = re.sub(r"\d+", " ", text)
        text = _WITH_REPORTS.sub(" ", text)
        if self.name_noise:
            text = self.name_noise.sub(" ", text)
        text = re.sub(_ORDINARY, "ordinary", text, flags=re.IGNORECASE)
        words = set(re.findall(r"[a-z]+", text.lower()))
        return words - _FILLER

    def _meeting_name(
        self, text: str, residual: set[str]
    ) -> tuple[Optional[str], bool]:
        """The meeting type a label names, and whether it names one at all."""
        for pattern, name in self.names:
            if pattern.search(text):
                return name, True
        # "Minutes - 26-11-2025", "21 February 2020": a paper of the
        # council's usual meeting, saying nothing more.
        if not residual:
            return self.ordinary_name, False
        if residual <= {"soko"}:
            # "SoKO Ordinary Meeting" is caught above; Kojonup's initials
            # alone say no more than an empty label.
            return self.ordinary_name, False
        return None, False

    def _rank(self, kind: str, label: str) -> int:
        """Lower is preferred when a meeting has two candidates for a slot."""
        rank = 0
        if _PACKET.search(label) or _COMBINED.search(label):
            # The bare agenda over the one bundled with its attachments.
            rank += 2
        if kind == AGENDA and _AMENDED.search(label):
            rank -= 1
        if kind == MINUTES:
            # Confirmed minutes supersede unconfirmed ones when both are up
            # (Narrogin posts each meeting's twice), and either beats a
            # summary (Cuballing, December 2020).
            if _UNCONFIRMED.search(label):
                rank += 2
            elif not _CONFIRMED.search(label):
                rank += 1
            if _SUMMARY.search(label):
                rank += 3
        return rank

    def _classify(
        self, label: str, css: str, url: str, doc_id: int, folder: _Folder
    ) -> Optional[_Document]:
        """The paper a library item is, or None if it is not a meeting's
        agenda or minutes."""
        tested = _READER_NOTE.sub(" ", label)
        if css and "doc-pdf" not in css:
            # Audio, video, links and Word copies: Yalgoo files a recording
            # as "Ordinary Council Meeting Minutes - Friday 1 May 2026".
            self.logger.debug(f"Not a PDF ({css}): {label!r} ({url})")
            return None
        if _NOT_THE_PAPER.search(_PACKET.sub(" ", tested)):
            self.logger.debug(f"Not the agenda or minutes: {label!r} ({url})")
            return None
        if _OTHER_BODIES.search(tested):
            self.logger.debug(f"Another body's paper: {label!r} ({url})")
            return None

        agenda = bool(_AGENDA_WORD.search(tested))
        minutes = bool(_MINUTES_WORD.search(tested))
        residual = self._residual_words(tested)
        if agenda != minutes:
            kind = AGENDA if agenda else MINUTES
        elif folder.kind and residual <= _NAME_WORDS | self.extra_name_words:
            # "21 February 2020" in "Agendas 2020", "AGM Electors Meeting -
            # 27 October 2021" in Boyup Brook's agendas: a label that is only
            # a meeting's name and date takes its folder's kind. One with
            # more ("2025/2026 Statutory Budget - Special Council Meeting")
            # is some other paper.
            kind = folder.kind
        else:
            self.logger.info(f"Neither agenda nor minutes: {label!r} ({url})")
            return None

        name, typed = self._meeting_name(tested, residual)
        if name is None:
            self.logger.info(f"Not a meeting's paper: {label!r} ({url})")
            return None

        date, month = self._read_date(tested, folder.year)
        pdf_month = None
        if self.numbered_months and date is None and month is None:
            numbered = _NUMBERED.match(tested)
            if numbered and 1 <= int(numbered.group(2)) <= 12:
                pdf_month = (int(numbered.group(1)), int(numbered.group(2)))
        document = _Document(
            kind=kind,
            name=name,
            url=url,
            label=label,
            folder_url=self._folder_url(folder),
            rank=self._rank(kind, label),
            doc_id=doc_id,
            date=date,
            month=month,
            typed=typed,
            pdf_month=pdf_month,
        )
        return document

    # --- month-only papers -----------------------------------------------------

    def _schedule(self) -> dict[tuple[int, int], datetime.date]:
        """(year, month) -> the one ordinary meeting the council's schedule
        page lists in that month. Read once, and only when needed."""
        if self._schedule_cache is not None:
            return self._schedule_cache
        self._schedule_cache = {}
        if not self.schedule_path:
            return self._schedule_cache
        url = urljoin(self.base_url, self.schedule_path)
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        main = soup.find("main") or soup
        found: dict[tuple[int, int], set[datetime.date]] = {}
        for block in main.find_all(["p", "li", "td", "h3", "h4"]):
            text = block.get_text(" ", strip=True)
            if self._names_another_meeting(text):
                # Cuballing's "Annual General Meeting of Electors - 4.30pm
                # Wednesday 4 February 2026" sits in the list above the
                # ordinary meeting of 18 February; counted, it would leave
                # February with two dates and so with none.
                continue
            date, _ = self._read_date(text, None)
            if date:
                found.setdefault((date.year, date.month), set()).add(date)
        self._schedule_cache = {
            key: dates.pop() for key, dates in found.items() if len(dates) == 1
        }
        if not self._schedule_cache:
            self.logger.warning(f"No meeting dates read from {url}")
        return self._schedule_cache

    def _names_another_meeting(self, text: str) -> bool:
        for pattern, name in self.names:
            if pattern.search(text):
                return name != self.ordinary_name
        return False

    def _date_month_only(self, documents: list[_Document]) -> list[_Document]:
        """Give a month-only paper the day of its meeting where the council
        names it (see the module docstring), and drop it where it does not."""
        known: dict[tuple[str, int, int], set[datetime.date]] = {}
        for document in documents:
            if document.date:
                date = document.date
                known.setdefault((document.name, date.year, date.month), set()).add(
                    date
                )

        for document in documents:
            if document.date is None and document.month is not None:
                year, month = document.month
                days = known.get((document.name, year, month), set())
                if len(days) == 1:
                    document.date = next(iter(days))
                elif (
                    not days
                    and document.name == self.ordinary_name
                    and self.schedule_path
                ):
                    document.date = self._schedule().get((year, month))
        if self.pdf_dates:
            self._dates_from_pdfs(
                [d for d in documents if d.date is None and (d.month or d.pdf_month)]
            )

        dated = []
        for document in documents:
            if document.date is None:
                self.dropped.append(document)
                self.logger.info(
                    f"No meeting day for {document.kind} {document.label!r} "
                    f"({document.url}); left out"
                )
                continue
            dated.append(document)
        return dated

    def _dates_from_pdfs(self, documents: list[_Document]) -> None:
        """Date month-only papers from their PDFs' first page (`pdf_dates`).

        Papers of one meeting type in one month are one meeting when there
        is at most one of each kind: the first of them, in `pdf_kinds`
        order, that gives a day in the label's month dates them all. Two
        papers of one kind (a special meeting's agenda and its amended
        agenda, or two meetings) are each dated from their own PDF. Only
        papers whose month is in a wanted year are read; the rest are left
        out as before.
        """
        wanted = self._wanted_years()
        groups: dict[tuple[str, int, int], list[_Document]] = {}
        for document in documents:
            year, month = document.month or document.pdf_month
            if year in wanted:
                groups.setdefault((document.name, year, month), []).append(document)

        def read(document: _Document) -> Optional[datetime.date]:
            year, month = document.month or document.pdf_month
            return meeting_date_from_pdf(
                self.fetcher,
                document.url,
                year,
                month,
                full_limit=self.pdf_full_limit,
                logger=self.logger,
            )

        def order(document: _Document):
            kind = (
                self.pdf_kinds.index(document.kind)
                if document.kind in self.pdf_kinds
                else len(self.pdf_kinds)
            )
            return (kind, document.rank, -document.doc_id)

        for group in groups.values():
            kinds = [d.kind for d in group]
            if len(kinds) == len(set(kinds)):
                date = None
                for document in sorted(group, key=order):
                    if document.kind in self.pdf_kinds:
                        date = read(document)
                    if date:
                        break
                targets = [(d, date) for d in group] if date else []
            else:
                targets = [(d, read(d)) for d in sorted(group, key=order)]
            for document, date in targets:
                if date:
                    self.logger.info(
                        f"{self.council_name}: {document.label!r} dated {date} "
                        f"from the PDF"
                    )
                    document.date = date

    # --- the scrape ----------------------------------------------------------

    def _apply_corrections(self, document: _Document) -> _Document:
        correction = self.corrections.get(document.url)
        if not correction:
            return document
        if "date" in correction:
            document.date = datetime.date.fromisoformat(correction["date"])
            document.month = None
        if "name" in correction:
            document.name = correction["name"]
        if "kind" in correction:
            document.kind = correction["kind"]
        if "time" in correction:
            document.time = correction["time"]
        return document

    def _meetings(self, documents: list[_Document]) -> list[ScraperReturn]:
        """Group papers into meetings by date and meeting type, and by time
        where a correction gives one: Boyup Brook held two special meetings
        on 2 March 2023, at 3.00 pm to appoint a CEO and at 3.30 pm to award
        a tender, and without the time their papers would be taken for one
        meeting's and one of each pair thrown away."""
        groups: dict[tuple[datetime.date, str, Optional[str]], dict[str, _Document]] = (
            {}
        )
        order = []
        for document in documents:
            key = (document.date, document.name, document.time)
            if key not in groups:
                groups[key] = {}
                order.append(key)
            slot = groups[key]
            current = slot.get(document.kind)
            # Lower rank wins; between equals, the later upload, which is
            # how a council replaces a paper (Yalgoo's two "2026-05 Ordinary
            # Council Meeting Agenda Friday 1 May 2026").
            if current is None or (document.rank, -document.doc_id) < (
                current.rank,
                -current.doc_id,
            ):
                slot[document.kind] = document

        # A paper whose label names no meeting type joins another meeting on
        # its date when that is the only one missing that paper: Boyup
        # Brook's "Minutes - 2 April 2020" and "Agenda - 27 October 2021"
        # are a special meeting's, by their covers, beside a "Special
        # Council Agenda" and "Special Council Minutes" of the same date. A
        # second candidate, or none, leaves it the ordinary meeting it
        # defaults to. Only a special meeting is a candidate: an electors'
        # meeting is held beside an ordinary one on the same evening often
        # enough (Boyup Brook, every February) that an ordinary meeting's
        # unlabelled minutes could otherwise land on it.
        for key in list(order):
            slot = groups[key]
            if any(d.typed for d in slot.values()):
                continue
            partners = [
                other
                for other in order
                if other != key
                and other[0] == key[0]
                and other[1] == "Special Council Meeting"
                and not set(groups[other]) & set(slot)
            ]
            if len(partners) == 1:
                groups[partners[0]].update(slot)
                order.remove(key)
                del groups[key]

        results = []
        for date, name, time in order:
            slot = groups[(date, name, time)]
            agenda, minutes = slot.get(AGENDA), slot.get(MINUTES)
            agenda_url = agenda.url if agenda else None
            minutes_url = minutes.url if minutes else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=time,
                    webpage_url=(agenda or minutes).folder_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        self._schedule_cache: Optional[dict] = None
        self.dropped: list[_Document] = []

        # Not caught: without the index there is no knowing which folders
        # hold the papers, and without a folder its year is missing.
        index = self.fetcher.fetch_with_requests(f"{self.base_url}/documents/")
        folders = self._folders(index, wanted)

        documents: list[_Document] = []
        seen: set[str] = set()
        for folder in folders:
            url = self._folder_url(folder)
            for label, css, doc_url, doc_id in self._folder_items(
                self.fetcher.fetch_with_requests(url), url
            ):
                if doc_url in seen or doc_url in self.wrong_documents:
                    continue
                seen.add(doc_url)
                document = self._classify(label, css, doc_url, doc_id, folder)
                if document:
                    documents.append(self._apply_corrections(document))

        documents = self._date_month_only(documents)
        results = [r for r in self._meetings(documents) if int(r.date[:4]) in wanted]
        if not results and self._new_year_not_filed_yet(index, wanted, folders):
            self.logger.warning(
                f"{self.council_name}: no {clock.current_year()} folder in the "
                f"library yet; last year's are there, so the first paper of the "
                f"year is not filed yet"
            )
            return []
        if not results:
            raise RuntimeError(
                f"{self.council_name}: no meetings with papers for {sorted(wanted)} "
                f"in {len(folders)} library folders; the library may have changed"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _new_year_not_filed_yet(
        self, index_html: str, wanted: set[int], folders: list[_Folder]
    ) -> bool:
        """Whether an empty run is the new year before its first paper.

        Production asks for the current year alone, and that year's folders
        do not exist until a paper is filed in them; the first meeting is
        often late February, so for weeks every January an honest library
        has nothing to give. That is not a failure when last year's folders
        are in the index (so it was read as it should be) and it is still
        the first quarter. Any other empty run raises: a folder for the year
        that yields nothing, a missing folder later in the year, or an index
        with no folders the scraper recognises at all.
        """
        year = clock.current_year()
        if wanted != {year} or clock.today().month > 3:
            return False
        if any(folder.year == year for folder in folders):
            return False
        return bool(self._folders(index_html, {year - 1}))


# The words a label may hold, besides dates and _FILLER, and still be only a
# meeting's name (see _classify).
_NAME_WORDS = frozenset(
    """
    ordinary ocm scm special electors elector annual general agm
    regional development assessment panel dap soko
    """.split()
)
