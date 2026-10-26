"""OpenCities content pages—meeting papers published as a document list.

Many small councils on Granicus's OpenCities CMS never turned on the meetings
module (`opencities.py`). They publish their papers on an ordinary content
page instead: accordions headed by year ("2026 Council Agendas", "Council
Meeting Minutes 2026", "2026 Agendas and Minutes"), each holding a list of
direct ``/files/assets/public/...`` (or ``/files/sharedassets/...``,
``/files/<guid>/...``) PDF links. There is no meeting record anywhere: every
link is one document, titled by hand, and the same meeting's agenda and
minutes can sit in different accordions. So this base reads documents, not
meetings, and groups them with `meeting_documents.group_documents`.

A page is one request whatever it holds, so a council costs one or two
requests a night. `pages` says which page carries which years, and a page is
only fetched when it can hold a year that was asked for.

What a document is, in order of trust:

1. **The link text.** "Ordinary Council Meeting - Agenda - 6 October 2026",
   "23 September 2026 - Unconfirmed Ordinary Council Meeting Minutes",
   "Public Agenda: Ordinary Council Meeting - 12 October 2026",
   "2026-08-25 Ordinary Council Agenda". The kind and the date usually come
   from here.
2. **The filename**, when the text leaves something out: Murweh's agenda
   links are titled "01 Council Meeting 20 January 2022" and only the folder
   or the filename says "agenda"; NPARC's are titled "January Council Meeting
   Agenda" and only the filename has the day
   ("...-27-january-2026-uploaded-on-website.pdf").
3. **The accordion heading**, for the kind ("2026 Agendas") and the year
   ("2026 Meeting Date, Booklets and Minutes").

A filename is never allowed to overrule the text, only to fill a gap or to
veto: a link labelled as the agenda whose file is called "...minutes..." is
the council's own mistake (NPARC's December 2025 "Council Meeting Agenda" is
the 17 December minutes), and storing it as the agenda would be wrong, so it
is dropped.

Dates the text gives only as a month ("January Council Meeting Agenda",
"Council Meeting - March 2023 - Agenda") are completed from the filename, or
from the one other paper of the same meeting in that month that has a day.
Failing both, the document is left out and logged—a meeting date is never
invented from a month.

These pages are typed by hand, and a few corrections follow from that, each
logged when it fires:

- A label year later than its accordion's, or years from it, is a typo
  (`_checked_date`).
- A label copied from the row above shows as a filename naming another date;
  the paper then ranks last, and moves to that date when a paper of the
  other kind is waiting there (`_follow_filenames`).
- A two-day meeting is dated by its first day (`_join_multi_day`).
- A paper dated on a Sunday is a typo and is left out (`_drop_sundays`).
- A Council meeting whose agenda and minutes name different meeting types
  ("Special Council Meeting - Agenda", "Ordinary Council Meeting - Confirmed
  Minutes" on the same day) is one meeting (`_join_split_council_meetings`).
- A label and filename that agree and are both wrong can only be caught
  from the PDF, and a paper that gives no day anywhere can only be dated
  from it; a subclass lists those in `misfiled`.
"""

from __future__ import annotations

import calendar
import datetime
import re
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.meeting_documents import (
    AGENDA,
    MINUTES,
    Document,
    group_documents,
    name_words,
)
from aus_council_scrapers.pdf_dates import PDF_FULL_LIMIT, meeting_date_from_pdf

# --- dates ----------------------------------------------------------------

# Months as councils actually type them: "Feburary" (NPARC), "Janaury"
# (Flinders' filenames). Only the first three letters decide the month.
_MONTH = (
    r"(?P<month>jan(?:uary|aury)?|feb(?:ruary|urary)?|mar(?:ch)?|apr(?:il)?|may|june?"
    r"|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?![a-z])"
)
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}

# A two-day meeting is "26-27 August 2025", "17 and 18 April 2023" or
# "October 28 & 29, 2024": the meeting is dated by its first day. A dash
# only counts unspaced, because "Agenda Part 1 - 20 May 2025" is not a
# meeting on the 1st.
_SECOND_DAY = r"(?:(?:[-–]|\s*(?:&|and|to)\s*)(?P<day2>\d{1,2})(?:st|nd|rd|th)?)?"

# "6 October 2026", "Monday 24th March 2025", "18, September 2023",
# "20-January-2026" (Murweh titles links with the filename), "6 February 24".
_DMY = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})(?:st|nd|rd|th)?{_SECOND_DAY}[\s,._-]*(?:of\s+)?"
    rf"{_MONTH}\.?[\s,._-]*(?P<year>\d{{4}}|\d{{2}})(?!\d)",
    re.IGNORECASE,
)
# "December 18, 2024", "December 14 2022" (Diamantina).
_MDY = re.compile(
    rf"{_MONTH}\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?!\d){_SECOND_DAY},?\s+"
    r"(?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)
# "2026-08-25" (Burdekin, Paroo), typed loosely: "2025-08 26", "2025- 08-12",
# "2021-01.21", "2024-2-20".
_ISO = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*[-._]\s*(?P<month>\d{1,2})\s*[-._ ]\s*(?P<day>\d{1,2})(?!\d)"
)
# "11.01.2023" (NPARC). Dots and slashes only: a dashed d-m-y is ambiguous
# with Burdekin's yy-mm-dd, handled by `_SHORT_ISO`.
_NUMERIC_DMY = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})(?!\d)"
)
# Burdekin's "22-03-22" and "22-04-12": yy-mm-dd, which only the accordion's
# year can tell apart from dd-mm-yy.
_SHORT_ISO = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{2})(?!\d)")
# A day and month with the year left to the accordion: "Ordinary Council
# Meeting - 20 February - Agenda" under "2024 Council Agendas",
# "December 16 - Minutes of Ordinary Council Meeting" under 2025.
_DM = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})(?:st|nd|rd|th)?{_SECOND_DAY}[\s_-]+{_MONTH}",
    re.IGNORECASE,
)
_MD = re.compile(rf"{_MONTH}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?!\d)", re.IGNORECASE)
_MONTH_WORD = re.compile(_MONTH, re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

# Filenames run dates together: "..._16012024___final.pdf" (ddmmyyyy,
# NPARC), "20260922ordinarycouncilagendapublic.pdf" (yyyymmdd, Burdekin).
_COMPACT_DMY = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
_COMPACT_YMD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")

# A start time written into the label. Only with am or pm: a bare "13.1" is
# an item number.
_STATED_TIME = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*[ap]\.?m\b\.?", re.IGNORECASE)

_WEEKDAY = re.compile(
    r"\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b",
    re.IGNORECASE,
)


def _make_date(year: int, month: int, day: int) -> Optional[datetime.date]:
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _month_number(name: str) -> int:
    return _MONTHS[name[:3].lower()]


@dataclass
class _Found:
    date: Optional[datetime.date]  # None when only the month is known
    year: Optional[int]
    month: Optional[int]
    span: tuple[int, int]
    days: int = 1  # how many days the meeting ran, for "20 and 21 November"


def _days(m: re.Match) -> int:
    second = m.groupdict().get("day2")
    if not second:
        return 1
    days = int(second) - int(m["day"]) + 1
    return days if 1 < days <= 3 else 1


def _date_in_text(text: str, section_year: Optional[int]) -> Optional[_Found]:
    """The meeting date a label states, as fully as it states it."""
    for pattern in (_DMY, _MDY):
        m = pattern.search(text)
        if m:
            date = _make_date(int(m["year"]), _month_number(m["month"]), int(m["day"]))
            if date:
                return _Found(date, date.year, date.month, m.span(), _days(m))
    for pattern in (_ISO, _NUMERIC_DMY):
        m = pattern.search(text)
        if m:
            date = _make_date(int(m["year"]), int(m["month"]), int(m["day"]))
            if date:
                return _Found(date, date.year, date.month, m.span())
    m = _SHORT_ISO.search(text)
    if m and section_year:
        a, b, c = (int(g) for g in m.groups())
        for date in (_make_date(a, b, c), _make_date(c, b, a)):
            if date and date.year == section_year:
                return _Found(date, date.year, date.month, m.span())
    if section_year:
        for pattern in (_DM, _MD):
            m = pattern.search(text)
            if m:
                date = _make_date(
                    section_year, _month_number(m["month"]), int(m["day"])
                )
                if date:
                    return _Found(date, date.year, date.month, m.span(), _days(m))
    m = _MONTH_WORD.search(text)
    if m:
        year = _YEAR.search(text)
        year = int(year.group(1)) if year else section_year
        if year:
            return _Found(None, year, _month_number(m["month"]), m.span())
    return None


# A two-day meeting in a filename: "...-23-24-september-2025" (NPARC). Turned
# into "23 and 24 september" before dashes become spaces, which would leave
# "23 24 september" and date the meeting by its second day. Only days one or
# two apart count: "agenda-part-1-20-may-2025" is part one of 20 May.
_FILE_TWO_DAYS = re.compile(
    rf"(?<!\d)(\d{{1,2}})-(\d{{1,2}})(?=[\s_-]+{_MONTH})", re.IGNORECASE
)


def _filename_text(stem: str) -> str:
    def two_days(m: re.Match) -> str:
        first, second = int(m.group(1)), int(m.group(2))
        return f"{first} and {second}" if 1 <= second - first <= 2 else m.group(0)

    return re.sub(r"[_\-]+", " ", _FILE_TWO_DAYS.sub(two_days, stem))


def _dates_in_filename(stem: str) -> list[datetime.date]:
    text = _filename_text(stem)
    dates = []
    for pattern in (_DMY, _MDY, _ISO, _NUMERIC_DMY):
        for m in pattern.finditer(text):
            month = m["month"]
            month = int(month) if month.isdigit() else _month_number(month)
            date = _make_date(int(m["year"]), month, int(m["day"]))
            if date:
                dates.append(date)
    # "2022_06_16_council_agenda" (Longreach): `_filename_text` turns the
    # underscores into spaces, which `_ISO` does not take between year and
    # month, so read the stem as it is too.
    for m in _ISO.finditer(stem):
        date = _make_date(int(m["year"]), int(m["month"]), int(m["day"]))
        if date and date not in dates:
            dates.append(date)
    for m in _COMPACT_DMY.finditer(stem):
        date = _make_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if date:
            dates.append(date)
    for m in _COMPACT_YMD.finditer(stem):
        date = _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if date:
            dates.append(date)
    return dates


def _day_in_filename(stem: str, year: int, month: int) -> Optional[datetime.date]:
    """The day a filename gives with no year, for a label that gives the month.

    Flinders' "Council Meeting - October 2022 - Agenda" is
    "agenda_with_appendices-11-oct.pdf"; NPARC's "November Ordinary Meeting
    Confirmed Minutes" under 2021 is "24_november_ordinary_council_...". The
    year is the label's or the accordion's, and only a day in the label's own
    month is taken, so a stray number cannot move the meeting.

    A number equal to the year's last two digits is the year, not the day:
    NPARC's February and March 2022 minutes are "feb_22_..." and
    "march_22_...", and its May 2020 minutes "may_20_...". Only an ordinal
    ("october_27th") makes such a number a day.
    """
    text = _filename_text(stem)
    days = set()
    for pattern in (_DM, _MD):
        for m in pattern.finditer(text):
            if int(m["day"]) == year % 100 and not re.search(
                r"\d(?:st|nd|rd|th)", m.group(0), re.IGNORECASE
            ):
                continue
            if _month_number(m["month"]) == month:
                date = _make_date(year, month, int(m["day"]))
                if date:
                    days.add(date)
    return days.pop() if len(days) == 1 else None


# A filename's leading number and the month straight after it: "05-may-...",
# "001-january-2026-...", "03march2026-...", "011-nov-..." (`numbered_files`).
_MONTH_SEQUENCE = re.compile(rf"^(\d{{1,3}})[\s_-]*{_MONTH}", re.IGNORECASE)


# --- what a link is --------------------------------------------------------

_MINUTES = re.compile(r"\bmin(?:ute|tue|uite)s?\b", re.IGNORECASE)
_DEFAULT_AGENDA = r"\bagendas?\b|\bbusiness\s+papers?\b"

# Papers filed beside the agenda and minutes that are neither: attachment
# books, late and supplementary items, officer and deputation presentations
# (Livingstone files a dozen a meeting under "Council Minutes"), workshop and
# briefing papers, meeting-date schedules and correspondence packets. A notice
# of meeting alone is not the agenda either (Whitsunday's special budget
# meetings have only a notice), but "Notice and Agenda" is.
_NOT_THE_PAPER = re.compile(
    r"attach|annex|appendi|supp?lement|suppliment|addend|errata|\blate\b"
    r"|\bitem\s*\d|\breports?\b|presentation|deputation|petition|workshop"
    r"|briefing|\bindex\b|table\s+of\s+contents|\bdates?\b|schedule"
    r"|correspondence|confidential|standing\s+orders|\bpolicy\b|procedures?"
    r"|additional\s+info"
    r"|\bnotice\b",
    re.IGNORECASE,
)
# The words in `_NOT_THE_PAPER` that make a paper late or supplementary,
# for `_minutes_misfiled_as_late`.
_LATE = re.compile(r"\b(?:supp?lement\w*|suppliment\w*|late)\b", re.IGNORECASE)
# "Agenda with Appendices" is the agenda, appendices bound in (Flinders,
# 2020), and so is "Agenda with Attachments" (Torres), "Agenda (incl
# Attachments)" and "Agenda and Attachments" (Armidale, one file each); only
# a paper that is the appendices or attachments is not. A supplementary
# agenda with its attachments is still refused for being supplementary.
_WITH_APPENDICES = re.compile(
    r"\b(agenda|minutes)\s*\(?\s*(?:with|incl(?:uding|\.)?|and|&)\s+"
    r"(?:appendi\w*|attachments?)\b\s*\)?",
    re.IGNORECASE,
)
_NOTICE_AND_AGENDA = re.compile(
    r"\bnotice\s+(?:and|&)\s+agenda\b|\bagenda\s+(?:and|&)\s+notice\b", re.IGNORECASE
)
# A file whose name says it is a supplementary, workshop or briefing paper,
# or starts with "attachment", is that, whatever its link says: Paroo links
# "2022-03-15 General Meeting Agenda" to "..._supplementary_agenda.pdf" beside
# the real one, and "2020-06-30 Special Council Meeting Agenda" to a
# councillors' workshop agenda.
_FILENAME_NOT_THE_AGENDA = re.compile(
    r"^attachment|supp?lement|suppliment|workshop|briefing|late[\s_-]*report",
    re.IGNORECASE,
)

# Minutes, best first: a confirmed set that was later amended replaces the
# confirmed one (Diamantina lists both), and either beats an unconfirmed or
# draft set of the same meeting.
_CONFIRMED = re.compile(r"(?<!un)(?<!un-)(?<!un )\bconfirmed\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"\bun[\s-]?confirmed\b|\bdraft\b", re.IGNORECASE)
_AMENDED = re.compile(r"\b(?:amended|updated|revised)\b", re.IGNORECASE)

# Agendas split into parts: "Agenda Part 2", "Part Two", "PART A",
# "Agenda (Part 1)", "Minutes_Part 3". Part one is the agenda proper, with
# the order of business; the rest are its reports.
_PART = re.compile(
    r"\bpart\s*[-_]?\s*(\d+|[a-h]\b|one|two|three|four|five|six)", re.IGNORECASE
)
_PART_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# What is left of a label once its date and kind are gone, that is still
# not part of the meeting's name.
_SIZE = re.compile(r"\(\s*[A-Z]+\s*,\s*[\d.]+\s*[KMG]?B\s*\)\s*$", re.IGNORECASE)
_NOISE = re.compile(
    r"\.pdf\b|\b(?:un[\s-]?)?confirmed\b|\bamended\b|\bupdated?\b|\brevised\b"
    r"|\bdraft\b|\bfinal\b|\bpublic\b|\bversion\b|\bweb\s*copy\b|\bcopy\b|\bweb\b"
    r"|\bcomplete\b|\breduced\b|\(\s*\d\s*\)|\bnotice\s+(?:and|&)\b|\b(?:and|&)\s+notice\b"
    r"|\bpart\s*[-_]?\s*(?:\d+|[a-h]\b|one|two|three|four|five|six)\b|\(\s*[a-h]\s*\)",
    re.IGNORECASE,
)
# A leading sequence number: "01.", "07.1", "05S-", "01 -", "14 - ".
_SEQUENCE = re.compile(r"^\s*\d{1,2}(?:\.\d)?[a-z]?\b[\s.:-]*", re.IGNORECASE)

# Words that say nothing about which meeting a paper is for, on top of
# meeting_documents' own: "Ordinary Council Meeting", "Council Meeting" and
# "General Meeting" are one meeting at Murweh and Paroo, and Diamantina's
# "Extraordinary Meeting of Council" minutes are filed as "Special".
# "counc" and "mee...ng" catch the typos ("Ordinary Counci Meeting",
# Livingstone 2022; "March Trustee Meeing Agenda", NPARC 2024).
_GROUPING_NOISE = re.compile(
    r"\b(?:ordinary|general|public|of|counc\w*|mee\w*ng)\b", re.IGNORECASE
)
_GROUPING_SYNONYMS = ((re.compile(r"\bextraordinary\b", re.IGNORECASE), "special"),)


# The words of a meeting name that only say which kind of Council meeting it
# was. A name with nothing left once they are gone is the Council itself, not
# a committee or the Trustee (`_join_split_council_meetings`). "Second" is
# left out on purpose: Livingstone's "Second Special Council Meeting" is a
# meeting of its own on the day of another.
_COUNCIL_ITSELF = re.compile(
    r"\b(?:ordinary|special|extraordinary|budget|adoption|general|council"
    r"|meeting|statutory|post|election|of|the|and)\b",
    re.IGNORECASE,
)

# Rank penalties, above every tier, part and size in `_rank`.
_DISAGREES = 10**13  # the filename names another date
_DAY_MOVED = 10**14  # moved onto the first day of a two-day meeting


def _body(words: str) -> frozenset:
    """Which body a paper is for, as grouping sees it ("Trustees" is "Trustee")."""
    return name_words(words)


def _balanced(text: str) -> str:
    """Drop brackets left unpaired once dates and kinds are cut out."""
    depth, kept = 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue
            depth -= 1
        kept.append(ch)
    out = "".join(kept)
    while depth:
        i = out.rfind("(")
        out = out[:i] + out[i + 1 :]
        depth -= 1
    return out


def _kib(size: str) -> float:
    m = re.search(r"([\d.]+)\s*([KMG]?)B", size, re.IGNORECASE)
    if not m:
        return 0.0
    scale = {"": 1 / 1024, "K": 1, "M": 1024, "G": 1024 * 1024}[m.group(2).upper()]
    return float(m.group(1)) * scale


def _part_number(text: str) -> int:
    m = _PART.search(text)
    if not m:
        return 0
    token = m.group(1).lower()
    if token.isdigit():
        return int(token)
    if token in _PART_WORDS:
        return _PART_WORDS[token]
    return ord(token) - ord("a") + 1


@dataclass(frozen=True)
class ContentPage:
    """One page of papers, and which meeting years it can carry.

    `holds` is called with a year and says whether the page may list papers
    for meetings in it; None means any year. It decides what production—one
    year a night—has to fetch.
    """

    url: str
    holds: Optional[Callable[[int], bool]] = None


@dataclass
class _Link:
    label: str
    url: str
    size_kib: float
    page_url: str
    section_year: Optional[int]
    section_kind: Optional[str]


@dataclass
class _Paper:
    kind: str
    date: Optional[datetime.date]
    year: int
    month: Optional[int]
    name: str
    words: str  # the name as grouping sees it
    rank: int
    link: _Link
    days: int = 1
    # Set only when the filename's dates disagree with the label's.
    file_dates: list = field(default_factory=list)


class OpenCitiesContentScraper(BaseScraper):
    """Councils whose papers are links on OpenCities content pages.

    A subclass supplies `pages`, and only what differs from the defaults:

    ``agenda_words``
        A pattern for what the council calls an agenda, when that is not
        "agenda" or "business paper"—NPARC's are "Booklets".
    ``not_the_paper``
        A further pattern of labels that are not agendas or minutes, on top
        of `_NOT_THE_PAPER`.
    ``meeting_words``
        A pattern for words in a meeting's own name that `_NOT_THE_PAPER`
        would otherwise read as a paper that is not the agenda or minutes.
        Hepburn held a "Confidential Meeting of Council" and published its
        public minutes; "confidential" refuses a confidential paper filed
        beside the real ones, not a meeting that is named that way. The
        words are ignored only for that check: the name keeps them.
    ``misfiled``
        Papers whose label and filename agree and are both wrong, or give
        no day at all, by filename: the meeting date the PDF itself gives,
        or None to leave the paper out. Nothing on the page can catch or
        date these, so each entry should say what the PDF reads.
    ``year_index`` and ``year_page``
        For a council with a page per year ("Council-Meetings-2026",
        "Business-Papers-and-Minutes-2026"): the page that links them, and a
        pattern with a ``year`` group that picks the year pages out of its
        links. The index costs one request and saves guessing at a page that
        does not exist yet, which is every January. It may be a sitemap.xml,
        whose ``<loc>`` entries are read as links. Each year page holds its
        own year only, so until the new year's page exists a run for that
        year finds no page (`_no_year_page`).
    ``page_headings``
        Tag names that head sections on a page with no accordions, such as
        Boulia's ``h2`` "2026 Meeting Agendas & Minutes" over ``strong``
        "Meeting Minutes". A heading with a year starts a section with that
        year; one that names only agendas or only minutes sets the kind. Off
        by default: links outside accordions otherwise have no heading.
    ``numbered_files``
        For a council whose filenames start with a sequence number:
        McKinlay's "05-may-confirmed-ordinary-meeting-minutes.pdf",
        "10-october-unconfirmed-ordinary-meeting-minutes.pdf" and
        "01-oct-confirmed-minutes.pdf" are ordinary meetings held on none of
        the 5th, the 10th or the 1st. A leading number followed by a month
        is then ignored when the file is read for a date, if it is
        zero-padded ("01-oct"), three digits long ("011-nov") or the month's
        own number ("05-may"); "17_january_ordinary_meeting_agenda.pdf"
        still reads as the 17th. Off by default, because elsewhere
        "04-april-2024-..." can be the 4th of April.
    ``month_only_fails``
        For a council whose papers mostly give only their month, so that a
        year can hold papers and yet no meeting with a day. Winton dates
        only its special meetings, and none before 26 July in 2024; Temora
        dated no meeting at all in 2024. Left alone, such a year returns
        [] with a warning, which main.py counts as a working council. Set,
        a run whose years hold month-only papers and no meeting raises,
        naming them. A year with no papers yet (early January) still only
        warns. Off by default: elsewhere a month-only paper is the odd one
        out, and its year has dated meetings beside it.

    ``pdf_dates``
        For a council that gives the day nowhere on the page: a meeting
        whose papers are all month-only, in a year being scraped, is dated
        from its papers' first page (`pdf_dates`), read in the order of
        ``pdf_kinds`` and stopping at the first that gives a day in the
        label's month. A month holding two papers of one kind for one body
        dates each paper from its own PDF instead. Costs one or two
        requests per meeting a night, so it is off by default; set
        ``pdf_full_limit`` to bound the size of a file read whole.

    and may override `link_label` where a link's own text does not say what
    it is (a table row's "Agenda", a list's "Business Paper").
    """

    pages: list[ContentPage] = []
    agenda_words: str = _DEFAULT_AGENDA
    not_the_paper: Optional[re.Pattern] = None
    meeting_words: Optional[re.Pattern] = None
    misfiled: dict[str, Optional[datetime.date]] = {}
    year_index: Optional[str] = None
    year_page: Optional[re.Pattern] = None
    page_headings: tuple[str, ...] = ()
    numbered_files: bool = False
    month_only_fails: bool = False
    pdf_dates: bool = False
    pdf_kinds: tuple[str, ...] = (AGENDA, MINUTES)
    pdf_full_limit: int = PDF_FULL_LIMIT

    # The accordions OpenCities renders for a document list, and the content
    # area that holds them. Links outside an accordion but in the content
    # area (Burdekin's current meeting) are read too, with no heading.
    section_selector = "div.accordion-list-item-container"
    heading_selector = ".item-text, h2, h3"
    content_selector = "#main-content"

    def __init__(self, council_name: str, state: str, base_url: str):
        super().__init__(council_name, state, base_url)
        self._agenda = re.compile(self.agenda_words, re.IGNORECASE)

    # --- what to fetch ------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _pages_for(self, wanted: set[int]) -> list[ContentPage]:
        pages = list(self.pages)
        if self.year_index:
            pages.extend(self._year_pages())
        return [
            page
            for page in pages
            if page.holds is None or any(page.holds(year) for year in wanted)
        ]

    def _year_pages(self) -> list[ContentPage]:
        """The per-year pages `year_index` links, each holding its own year.

        An index that links none is a page this class no longer
        understands, not a council with no meetings, so it raises.
        """
        html = self.fetcher.fetch_with_requests(self.year_index)
        with warnings.catch_warnings():
            # A sitemap is XML; html.parser reads its <loc> tags well enough.
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(html, "html.parser")
        hrefs = [a["href"] for a in soup.find_all("a", href=True)]
        # The index may be the site's sitemap.xml: Goondiwindi's per-year
        # minutes pages ("Previous-Meeting-Minutes/2021-Minutes") are linked
        # from no menu or page, only listed there.
        hrefs += [loc.get_text(strip=True) for loc in soup.find_all("loc")]
        found: dict[str, int] = {}
        for href in hrefs:
            url = urljoin(self.year_index, href).split("#")[0]
            m = self.year_page.search(url)
            if m:
                found.setdefault(url, int(m["year"]))
        if not found:
            raise RuntimeError(
                f"{self.council_name}: no year pages on {self.year_index}"
            )
        return [
            ContentPage(url, holds=lambda y, page_year=year: y == page_year)
            for url, year in found.items()
        ]

    # --- reading a page -----------------------------------------------------

    def _section_kind(self, heading: str) -> Optional[str]:
        agenda = bool(self._agenda.search(heading))
        minutes = bool(_MINUTES.search(heading))
        if agenda and not minutes:
            return AGENDA
        if minutes and not agenda:
            return MINUTES
        return None

    @staticmethod
    def _is_document(href: str) -> bool:
        path = urlparse(href).path.lower()
        return "/files/" in path and path.endswith(".pdf")

    def _link(self, a: Tag, page_url: str, year, kind) -> Optional[_Link]:
        href = a.get("href", "")
        if not self._is_document(href):
            return None
        info = a.select_one(".file-info")
        size = info.get_text(" ", strip=True) if info else ""
        if info:
            info.extract()
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        label = _SIZE.sub("", label).strip()
        # Labels typed as the filename end in ".pdf" ("10. 30 October
        # 2024.pdf", Goondiwindi), which a sequence number then swallows.
        label = re.sub(r"\.pdf$", "", label, flags=re.IGNORECASE).strip()
        label = self.link_label(a, label)
        if label is None:
            return None
        label = re.sub(r"\s+", " ", label).strip()
        return _Link(label, urljoin(page_url, href), _kib(size), page_url, year, kind)

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        """The label to read a link by; by default its own text.

        A subclass whose links say only "Agenda" or "Business Paper"
        returns the meeting and date they sit under as well, from the table
        row or heading the page puts them in. None leaves the link out: a
        link the page files under the wrong meeting, whose file is also
        listed under the right one.
        """
        return label

    def _links(self, html: str, page_url: str) -> list[_Link]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one(self.content_selector) or soup
        links: list[_Link] = []
        for section in content.select(self.section_selector):
            heading = section.select_one(self.heading_selector)
            heading = heading.get_text(" ", strip=True) if heading else ""
            year = _YEAR.search(heading)
            year = int(year.group(1)) if year else None
            kind = self._section_kind(heading)
            for a in section.find_all("a", href=True):
                link = self._link(a, page_url, year, kind)
                if link:
                    links.append(link)
            section.decompose()
        # Links outside any accordion. With `page_headings` set, the
        # headings passed on the way down give each its year and kind.
        year = kind = None
        for el in content.find_all(True):
            if el.name in self.page_headings and not el.find_parent("a"):
                heading = el.get_text(" ", strip=True)
                found = _YEAR.search(heading)
                if found:
                    year, kind = int(found.group(1)), self._section_kind(heading)
                elif self._section_kind(heading):
                    kind = self._section_kind(heading)
            elif el.name == "a" and el.get("href"):
                link = self._link(el, page_url, year, kind)
                if link:
                    links.append(link)
        return links

    # --- what a link is -----------------------------------------------------

    def _kind(self, label: str, stem: str, section_kind: Optional[str]):
        """(kind, from_label), or None when nothing says which paper it is."""
        agenda = bool(self._agenda.search(label))
        minutes = bool(_MINUTES.search(label))
        if agenda != minutes:
            return (AGENDA if agenda else MINUTES), True
        if agenda and minutes:
            return (section_kind, False) if section_kind else None
        # No kind in the label. Only a label that names a meeting may take
        # its kind from elsewhere: Livingstone's "13.1 Development
        # Application D-489-2022 - 9 December 2025", filed under "Council
        # Minutes", is an officer's presentation.
        if not re.search(r"\bmeeting", label, re.IGNORECASE):
            return None
        stem_text = stem.replace("_", " ").replace("-", " ")
        agenda = bool(self._agenda.search(stem_text))
        minutes = bool(_MINUTES.search(stem_text))
        if agenda != minutes:
            return (AGENDA if agenda else MINUTES), False
        return (section_kind, False) if section_kind else None

    def _contradicted(self, kind: str, stem: str) -> bool:
        """Whether the filename says the label is wrong about the paper."""
        stem_text = stem.replace("_", " ").replace("-", " ")
        agenda = bool(self._agenda.search(stem_text))
        minutes = bool(_MINUTES.search(stem_text))
        if kind == AGENDA:
            return (minutes and not agenda) or bool(
                _FILENAME_NOT_THE_AGENDA.search(stem)
            )
        return agenda and not minutes

    def _rank(self, kind: str, label: str, from_label: bool, size_kib: float) -> int:
        if kind == MINUTES:
            if _UNCONFIRMED.search(label):
                tier = 3
            elif _CONFIRMED.search(label):
                tier = 0 if _AMENDED.search(label) else 1
            else:
                tier = 2
        else:
            tier = 1 if _AMENDED.search(label) else 0
        if not from_label:
            tier += 5
        # The larger file breaks a tie: where a council lists two "Public
        # Agenda" links for one meeting, the 146 KB one is the late item and
        # the 21 MB one the agenda (Diamantina, 15 December 2025).
        return (tier * 100 + _part_number(label)) * 10**10 - int(size_kib)

    def _name(self, label: str, found: Optional[_Found]) -> str:
        """The meeting type, in the council's words."""
        text = label
        if found:
            text = text[: found.span[0]] + " " + text[found.span[1] :]
        text = _STATED_TIME.sub(" ", text.replace("_", " "))
        # Labels that are filenames ("01-Agenda-Council-Meeting-...pdf").
        if not re.search(r"\s", text.strip()) or re.search(r"\w-\w+-\w", text):
            text = re.sub(r"(?<=\w)-(?=\w)", " ", text)
        text = _SEQUENCE.sub("", text)
        text = self._agenda.sub(" ", text)
        text = _MINUTES.sub(" ", text)
        text = _NOISE.sub(" ", text)
        text = _MONTH_WORD.sub(" ", text)
        text = _WEEKDAY.sub(" ", text)
        text = re.sub(r"\(\s*\)", " ", text)
        # Rejoin, dropping the separators the removals left dangling.
        parts = [
            _balanced(re.sub(r"\s+", " ", p).strip(" ,.:;"))
            for p in re.split(r"\s+[-–—:]+\s*|\s*[-–—:]+\s+|:", text)
        ]
        parts = [
            p
            for p in parts
            if p and p.lower() not in ("of", "and", "the") and not p.isdigit()
        ]
        # Flinders writes "Council Meeting - 24 January 2024 - Special Meeting
        # - Agenda": the meeting is the special meeting.
        if (
            len(parts) > 1
            and parts[0].lower() == "council meeting"
            and any(re.search(r"\bmeeting\b", p, re.IGNORECASE) for p in parts[1:])
        ):
            parts = parts[1:]
        name = " - ".join(parts)
        # Numbers left over are version stamps ("updated 24.2.25") or
        # financial years ("Budget 20/21"), not part of the meeting's name.
        name = re.sub(r"(?<![\w])[\d./]+(?![\w])", " ", name)
        # "2020-03-17 General Council Council Agenda" (Paroo).
        name = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+", " ", name).strip(" -")
        name = re.sub(r"(?:\s+-)+$", "", name)
        name = re.sub(r"^(?:of|for|the)\s+", "", name, flags=re.IGNORECASE).strip()
        # "Special Meeting Agenda and Business Papers" (Burke) leaves the
        # "and" that joined the two kinds of paper.
        name = re.sub(r"(?:\s+(?:and|&))+$", "", name, flags=re.IGNORECASE).strip()
        if not name:
            return "Council Meeting"
        if not re.search(r"\b(?:mee\w*ng|committee)\b", name, re.IGNORECASE):
            name += " Meeting"
        return name

    @staticmethod
    def _grouping_name(name: str) -> str:
        text = _GROUPING_NOISE.sub(" ", name)
        for pattern, replacement in _GROUPING_SYNONYMS:
            text = pattern.sub(replacement, text)
        return re.sub(r"\s+", " ", text).strip() or "council"

    def _minutes_misfiled_as_late(self, label: str, stem: str) -> Optional[str]:
        """The label to read, when a "supplementary" or "late" link is minutes.

        Paroo links "2022-03-15 General Meeting Agenda (Supplementary)" to
        "2022_03_15_ordinary_council_meeting_minutes___confirmed.pdf", the
        15 March 2022 minutes. The label is refused for the word that would
        make it a late paper; the filename says what it is. This is the
        filename veto of `_contradicted` run the other way, and only for
        labels refused for nothing else.
        """
        rest = _LATE.sub(" ", label)
        if rest == label or _NOT_THE_PAPER.search(
            _NOTICE_AND_AGENDA.sub(" agenda ", rest)
        ):
            return None
        stem_text = stem.replace("_", " ").replace("-", " ")
        if not _MINUTES.search(stem_text) or self._agenda.search(stem_text):
            return None
        if _FILENAME_NOT_THE_AGENDA.search(stem):
            return None
        return rest

    def _paper(self, link: _Link) -> Optional[_Paper]:
        label = link.label
        stem = unquote(urlparse(link.url).path.rsplit("/", 1)[-1])
        filename = stem
        stem = re.sub(r"\.pdf$", "", stem, flags=re.IGNORECASE)

        # "Notice and Agenda" is the agenda; any other notice is not, and
        # neither is anything else `_NOT_THE_PAPER` names.
        forced_kind = None
        label = _WITH_APPENDICES.sub(r"\1", label)
        checked = self.meeting_words.sub(" ", label) if self.meeting_words else label
        if _NOT_THE_PAPER.search(_NOTICE_AND_AGENDA.sub(" agenda ", checked)):
            rest = self._minutes_misfiled_as_late(label, stem)
            if rest is None:
                return None
            self.logger.info(
                f"{self.council_name}: {label!r} is file {filename!r}; "
                f"reading it as the minutes"
            )
            label, forced_kind = rest, (MINUTES, False)
        if self.not_the_paper and self.not_the_paper.search(label):
            return None

        kind = forced_kind or self._kind(label, stem, link.section_kind)
        if kind is None:
            return None
        kind, from_label = kind
        if from_label and self._contradicted(kind, stem):
            self.logger.info(
                f"{self.council_name}: skipping {label!r}: its file {stem!r} is "
                f"not the {kind}"
            )
            return None

        dating_stem = self._dating_stem(stem)
        file_dates = _dates_in_filename(dating_stem)
        found = _date_in_text(label.replace("_", " "), link.section_year)
        if filename in self.misfiled:
            # Checked before anything else, so a label with no date at all
            # can be dated too: Boulia's "2026-2027 Budget Meeting of
            # Council" names neither day nor month, in its text or its file.
            date = self.misfiled[filename]
            self.logger.info(
                f"{self.council_name}: {label!r} is file {filename!r}; "
                + (f"dating it {date}" if date else "leaving it out")
            )
            if date is None:
                return None
            year, month, file_dates = date.year, date.month, [date]
            days = found.days if found else 1
        elif found is None:
            # No date in the label at all ("2024 Post Election Confirmed
            # Minutes", NPARC): the filename's, when it has exactly one in
            # the accordion's year.
            candidates = {
                d
                for d in file_dates
                if link.section_year is None or d.year == link.section_year
            }
            if len(candidates) != 1:
                return None
            date = candidates.pop()
            year, month, days = date.year, date.month, 1
        else:
            days = found.days
            date = self._checked_date(found, link)
            month = found.month
            year = date.year if date else found.year
            if date is None:
                # Month only in the label: the day may be in the filename,
                # with its year or without.
                date = next(
                    (d for d in file_dates if d.year == year and d.month == month),
                    None,
                )
                if date is None and not file_dates and month:
                    date = _day_in_filename(dating_stem, year, month)
        # A filename with a full date that is not the label's is a sign the
        # label was copied from the row above: Whitsunday lists three files
        # as "10 August 2022 - Ordinary Council Meeting Minutes", named
        # 10-august-2022-..., 27-july-2022-... and 20-july-2022-special-....
        # Such a paper ranks below any whose filename agrees, and
        # `_follow_filenames` may move it to the meeting its file names.
        disagrees = bool(found and found.date and file_dates and date not in file_dates)
        time = _STATED_TIME.search(label)
        name = self._name(label, found)
        words = self._grouping_name(name)
        if time:
            # Two special meetings on one day differ only by their start
            # (Livingstone, 18 October 2024: "11am" and "12.30pm").
            words += " " + time.group().replace(" ", "")
        return _Paper(
            kind=kind,
            date=date,
            year=year,
            month=month,
            name=name,
            words=words,
            rank=self._rank(kind, label, from_label, link.size_kib)
            + (_DISAGREES if disagrees else 0),
            link=link,
            days=days,
            file_dates=file_dates if disagrees else [],
        )

    def _dating_stem(self, stem: str) -> str:
        """The filename as it is read for a date (`numbered_files`)."""
        if not self.numbered_files:
            return stem
        m = _MONTH_SEQUENCE.match(stem)
        if m and (
            m.group(1).startswith("0")
            or len(m.group(1)) > 2
            or int(m.group(1)) == _month_number(m["month"])
        ):
            return stem[m.start("month") :]
        return stem

    def _checked_date(self, found: _Found, link: _Link) -> Optional[datetime.date]:
        """The label's date, or the accordion's year where the label's is a typo.

        A paper filed under a later year than its date is ordinary—December's
        minutes are confirmed and posted in January. One filed under an
        *earlier* year than its date, or years away from it, is a typo in the
        label: Whitsunday's "26 March 2026 - Confirmed Ordinary Council Meeting
        Minutes" sits under 2025 beside the 26 March 2025 agenda, and
        Livingstone's "20 December 2000" agenda under 2022. The exceptions are
        a date still to come, which is an upcoming meeting posted before its
        year's accordion exists, and a January date one year on, which is the
        same paper after its meeting has passed.
        """
        date, section_year = found.date, link.section_year
        if date is None or section_year is None or date.year == section_year:
            return date
        if date.year == section_year - 1:
            return date
        if date.year > section_year and date >= clock.today():
            return date
        # A January meeting filed under December's year is that case once
        # the meeting has passed and nobody moved the paper; re-dating it a
        # year early would drop it from its own year's run the day after.
        if date.year == section_year + 1 and date.month == 1:
            return date
        corrected = _make_date(section_year, date.month, date.day)
        self.logger.info(
            f"{self.council_name}: {link.label!r} is filed under {section_year}; "
            f"dating it {corrected}, not {date}"
        )
        return corrected

    # --- month-only papers --------------------------------------------------

    def _complete_months(
        self, papers: list[_Paper], wanted: Optional[set[int]] = None
    ) -> list[_Paper]:
        """Give a month-only paper the day of its meeting's other paper.

        NPARC titles both papers by month ("February Council Meeting Agenda",
        "February Ordinary Council Meeting Minutes - CONFIRMED") and usually
        only one filename carries the day. One body meets once a month, so the
        other paper of the same meeting in the same month fixes the date—but
        only when exactly one such date exists, and only when that meeting
        has no paper of this kind already. Winton held two special meetings
        in April 2026 and lists "Special Meeting Business Paper 30 APRIL"
        and its minutes beside a "Special Meeting Business Paper APRIL" and
        "Minutes Special Meeting APRIL": the month-only pair is the other
        meeting, whose day the page never gives.
        """
        dated = [p for p in papers if p.date]
        complete = list(dated)
        # Kept for `month_only_fails`.
        self._month_only: list[_Paper] = []
        pending = []
        for paper in papers:
            if paper.date:
                continue
            body = _body(paper.words)
            days = {
                p.date
                for p in dated
                if p.kind != paper.kind
                and p.date.year == paper.year
                and p.date.month == paper.month
                and _body(p.words) == body
                and not any(
                    q.kind == paper.kind and q.date == p.date and _body(q.words) == body
                    for q in dated
                )
            }
            if len(days) == 1:
                paper.date = days.pop()
                complete.append(paper)
            else:
                pending.append(paper)
        complete.extend(self.date_month_only(pending, wanted))
        if self.pdf_dates:
            complete.extend(
                self._dates_from_pdfs([p for p in pending if p.date is None], wanted)
            )
        for paper in pending:
            if paper.date is None:
                self._month_only.append(paper)
                self.logger.info(
                    f"{self.council_name}: leaving out {paper.link.label!r}: "
                    f"it gives only {calendar.month_name[paper.month]} "
                    f"{paper.year}"
                )
        return complete

    def date_month_only(
        self, papers: list[_Paper], wanted: Optional[set[int]]
    ) -> list[_Paper]:
        """Date month-only papers from a source this class does not read.

        Called with the papers still undated once the page and the other
        paper of the same meeting have been tried, before `pdf_dates`. A
        subclass sets `date` on the ones it can date and returns them;
        whatever it leaves undated is left out and logged as usual. Temora
        reads the day from the title of the meeting's recording. Nothing by
        default.
        """
        return []

    def _dates_from_pdfs(
        self, papers: list[_Paper], wanted: Optional[set[int]]
    ) -> list[_Paper]:
        """Date month-only papers from their PDFs (`pdf_dates`); the dated ones."""
        groups: dict[tuple, list[_Paper]] = {}
        for paper in papers:
            if paper.month is None or (wanted and paper.year not in wanted):
                continue
            groups.setdefault((paper.year, paper.month, _body(paper.words)), []).append(
                paper
            )

        def order(p: _Paper):
            kind = self.pdf_kinds.index(p.kind) if p.kind in self.pdf_kinds else 99
            return (kind, p.rank)

        def read(paper: _Paper) -> Optional[datetime.date]:
            return meeting_date_from_pdf(
                self.fetcher,
                paper.link.url,
                paper.year,
                paper.month,
                full_limit=self.pdf_full_limit,
                logger=self.logger,
            )

        dated = []
        for group in groups.values():
            kinds = [p.kind for p in group]
            if len(kinds) == len(set(kinds)):
                # One meeting: the first paper that gives the day dates both.
                date = None
                for paper in sorted(group, key=order):
                    if paper.kind in self.pdf_kinds:
                        date = read(paper)
                    if date:
                        break
                targets = [(p, date) for p in group] if date else []
            else:
                # Two papers of one kind: more than one meeting, so each
                # paper is dated by itself.
                targets = [(p, read(p)) for p in group]
            for paper, date in targets:
                if date:
                    self.logger.info(
                        f"{self.council_name}: {paper.link.label!r} dated {date} "
                        f"from the PDF"
                    )
                    paper.date = date
                    dated.append(paper)
        return dated

    def _follow_filenames(self, papers: list[_Paper]) -> list[_Paper]:
        """Move a mislabelled paper to the meeting its filename names.

        Only where that is the one meeting the file can be: a paper of the
        other kind, for the same body, on the filename's date, and nothing of
        this kind there already. Murweh's "13 Council Meeting 17 November
        2023" agenda is "ordinary_council_meeting_16_november_2023" beside
        "13 Council Meeting 16 November 2023" minutes.

        A paper whose file is already there, uploaded twice under one name,
        is that paper listed again and is dropped. Hope Vale links
        ".../february/confirmed-council-minutes-21st-january-2026.pdf" as
        "Confirmed Council Minutes 15th December 2025" beside the copy in
        ".../january/" labelled as the 21 January minutes; left in, it
        became the minutes of the 15 December meeting.
        """
        kept = []
        for paper in papers:
            if not paper.file_dates:
                kept.append(paper)
                continue
            name = paper.link.url.rsplit("/", 1)[-1].lower()
            copy = next(
                (
                    q
                    for q in papers
                    if q is not paper
                    and q.kind == paper.kind
                    and q.date in paper.file_dates
                    and q.link.url.rsplit("/", 1)[-1].lower() == name
                ),
                None,
            )
            if copy is not None:
                self.logger.info(
                    f"{self.council_name}: leaving out {paper.link.label!r}: "
                    f"its file {name!r} is the {copy.date} {paper.kind}"
                )
                continue
            kept.append(paper)
            targets = {
                d
                for d in paper.file_dates
                if any(
                    q.kind != paper.kind
                    and q.date == d
                    and _body(q.words) == _body(paper.words)
                    for q in papers
                )
                and not any(
                    q is not paper
                    and q.kind == paper.kind
                    and q.date == d
                    and _body(q.words) == _body(paper.words)
                    for q in papers
                )
            }
            if len(targets) == 1:
                target = targets.pop()
                self.logger.info(
                    f"{self.council_name}: {paper.link.label!r} is file "
                    f"{paper.link.url.rsplit('/', 1)[-1]!r}; dating it {target}"
                )
                paper.date = target
                paper.rank -= _DISAGREES
        return kept

    def _drop_sundays(self, papers: list[_Paper]) -> list[_Paper]:
        """Leave out papers dated on a Sunday, when no council meets.

        Every one found is a typo that would otherwise be a meeting that never
        happened: Livingstone's "19 January 2020 - Agenda Part One" filed
        beside the 19 January 2021 papers, NPARC's "tuesday_26th_july_2020"
        minutes (26 July 2020 was a Sunday; the Tuesday was the 28th).
        """
        kept = []
        for paper in papers:
            if paper.date.weekday() == 6:
                self.logger.info(
                    f"{self.council_name}: leaving out {paper.link.label!r}: "
                    f"{paper.date} is a Sunday"
                )
                continue
            kept.append(paper)
        return kept

    @staticmethod
    def _join_multi_day(papers: list[_Paper]) -> list[_Paper]:
        """Date every paper of a two-day meeting by its first day.

        Livingstone's "Ordinary Council Meeting - 20 and 21 November 2023 -
        Confirmed Minutes" has its agenda in parts dated by the day each was
        taken: "20 November 2023 - Part One", "21 November 2023 - Agenda -
        Part Two". Left alone, the second day becomes a meeting of its own
        whose agenda is part two. A paper moved onto the first day ranks
        below one already there, so the first day's part one stays the agenda.
        """
        spans = [
            (p.date, p.date + datetime.timedelta(days=p.days - 1), p.words)
            for p in papers
            if p.days > 1
        ]
        for paper in papers:
            for first, last, words in spans:
                if first < paper.date <= last and _body(paper.words) == _body(words):
                    shift = (paper.date - first).days
                    paper.date = first
                    paper.rank += shift * _DAY_MOVED
        return papers

    # --- the run ------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        links: list[_Link] = []
        pages = self._pages_for(wanted)
        if not pages:
            # Only a council with a page per year gets here: the index was
            # read and linked year pages, but none for the years asked.
            return self._no_year_page(wanted)
        for page in pages:
            # A page is the whole of what it holds, so a failed fetch is not
            # a short year but a missing one. Raise rather than return
            # whatever the other page had; main.py would count an empty or
            # short list as a working council.
            html = self.fetcher.fetch_with_requests(page.url)
            links.extend(self._links(html, page.url))

        # A file listed twice is one paper. Only a link that reads as a paper
        # claims its file: NPARC links the 17 December 2025 minutes once as
        # "December - Council Meeting Agenda" (refused, the file is minutes)
        # and once as "December 17 - Minutes of Ordinary Council Meeting".
        seen: set[str] = set()
        papers = []
        for link in links:
            if link.url in seen:
                continue
            paper = self._paper(link)
            if paper:
                seen.add(link.url)
                papers.append(paper)

        papers = self._complete_months(papers, wanted)
        papers = self._join_multi_day(self._follow_filenames(papers))
        papers = self._drop_sundays(papers)
        papers = [p for p in papers if p.date.year in wanted]
        by_url = {p.link.url: p for p in papers}
        documents = [
            Document(
                kind=p.kind, title=p.words, date=p.date, url=p.link.url, rank=p.rank
            )
            for p in papers
        ]

        results = []
        for meeting in group_documents(documents, re.compile(r"(?!x)x")):
            paper = by_url[meeting.agenda_url or meeting.minutes_url]
            results.append(
                ScraperReturn(
                    name=paper.name,
                    date=meeting.date.isoformat(),
                    time=meeting.stated_time,
                    webpage_url=paper.link.page_url,
                    agenda_url=meeting.agenda_url,
                    minutes_url=meeting.minutes_url,
                    download_url=meeting.agenda_url or meeting.minutes_url,
                )
            )
        results = self._join_split_council_meetings(results)
        results.sort(key=lambda r: (r.date, r.name), reverse=True)

        if not links:
            # Every page was read and none had a single paper on it. That is
            # not a quiet year but a page this class no longer understands,
            # or a challenge page served with a 200 (every host here is
            # behind Akamai). main.py would report an empty list as a working
            # council, so fail instead.
            raise RuntimeError(
                f"{self.council_name}: no /files/ PDF links on "
                f"{[p.url for p in pages]}"
            )
        undated = [p for p in self._month_only if p.year in wanted]
        if not results and undated and self.month_only_fails:
            # Papers for the years asked, but none that gives its meeting's
            # day (`month_only_fails`). That is not a quiet year: the
            # meetings are there and this class cannot date them.
            raise RuntimeError(
                f"{self.council_name}: no meeting in {sorted(wanted)} gives its "
                f"day; {len(undated)} papers give only their month, such as "
                f"{[p.link.label for p in undated[:3]]}"
            )
        if not results:
            # Papers, but none for the years asked: early January, before
            # the year's first meeting is posted.
            self.logger.warning(
                f"{self.council_name}: no meetings in {sorted(wanted)} among "
                f"{len(links)} links"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _no_year_page(self, wanted: set[int]) -> list[ScraperReturn]:
        """No page can hold the years asked for.

        Every January, until the council makes the new year's page: Bulloo,
        Snowy Monaro and Torres each name a page by its year, and their
        archives hold only past years. That is a quiet start to the year,
        not a broken scraper, so it warns and returns nothing, as an empty
        page would. But only for a while. A past year with no page, or a
        year three months old with none, means the index no longer leads
        to the papers, and main.py would count an empty list as a working
        council, so that raises.
        """
        today = clock.today()
        overdue = sorted(
            y for y in wanted if y < today.year or (y == today.year and today.month > 3)
        )
        if overdue:
            raise RuntimeError(
                f"{self.council_name}: no page holds {overdue} "
                f"(index {self.year_index})"
            )
        self.logger.warning(
            f"{self.council_name}: no page for {sorted(wanted)} yet "
            f"(index {self.year_index})"
        )
        return []

    def _join_split_council_meetings(
        self, results: list[ScraperReturn]
    ) -> list[ScraperReturn]:
        """Join a Council meeting whose two papers name different meeting types.

        Livingstone files the minutes of its 17 and 24 April 2025 special
        meetings as "Ordinary Council Meeting - Confirmed Minutes", and
        Whitsunday the minutes of its 15 July 2020 special budget meeting as
        "Ordinary Council Meeting"; each PDF reads "Special Meeting". Grouping
        joins papers by name, so each became a special meeting with only its
        agenda and an ordinary meeting, which never happened, with only the
        minutes.

        A council meets as a council once a day, so where one record of the
        Council itself has only an agenda and one has only minutes on the
        same day, they are one meeting, named as the agenda names it.
        Committees and Trustee meetings keep their own name and are never
        joined, nor are two records whose stated times differ.
        """
        by_date: dict[str, list[ScraperReturn]] = {}
        for r in results:
            if not _COUNCIL_ITSELF.sub(" ", r.name).strip(" -&,()"):
                by_date.setdefault(r.date, []).append(r)
        dropped = set()
        for date, records in by_date.items():
            agendas = [r for r in records if r.agenda_url and not r.minutes_url]
            minutes = [r for r in records if r.minutes_url and not r.agenda_url]
            if len(agendas) != 1 or len(minutes) != 1:
                continue
            agenda, minute = agendas[0], minutes[0]
            if agenda.time and minute.time and agenda.time != minute.time:
                continue
            self.logger.info(
                f"{self.council_name}: {date} {minute.name!r} minutes are the "
                f"{agenda.name!r}'s"
            )
            agenda.minutes_url = minute.minutes_url
            agenda.time = agenda.time or minute.time
            dropped.add(id(minute))
        return [r for r in results if id(r) not in dropped]
