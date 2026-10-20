"""What `LGASAFunnelbackScraper` needs for the regional LGA SA councils.

Everything about fetching, robots.txt, the crawl delay and assembling
meetings is in `aus_council_scrapers/lgasa.py`. These councils differ from
the metropolitan ones in ways the base class has no setting for. All of it
is handled here rather than in the base class, so the councils already
recorded on it are untouched.

**Papers that are not a meeting's agenda or minutes, titled as if they
were.** Berri Barmera and Renmark Paringa file the papers for workshops,
briefing sessions and informal gatherings under the same committee label as
their council meetings, and title them like council papers: "Agenda -
Briefing Session of Council - 8 September 2026", "Informal Gathering Agenda -
Budget Workshop - 1 April 2026". These are informal gatherings under the
Local Government Act 1999 (SA), at which no decisions may be made. Berri
Barmera files each meeting's confidential papers, once released, a few days
away from the meeting ("RELEASED - Confidential Ordinary Meeting of Council
- 23 April 2023", for the meeting of the 24th). The base class groups on
committee and date, so each of these became a "Council Meeting" that never
happened. `skip_titles` names, per council, the titles to drop before
grouping.

**Meeting dates typed wrong.** The listing's meeting date is typed by hand
for each document, and on these councils it is wrong more often than the
title is: Wattle Range filed the minutes of its 13 October 2020 meeting
under 1 October, Mid Murray filed its 14 July 2020 agenda under 14 June,
and Naracoorte Lucindale filed both papers of its 22 March 2022 meeting
under the 17th (a Thursday; the council meets on Tuesdays). So a document is
grouped under the date its title states, when the title states a full date
within `TITLE_DATE_WINDOW_DAYS` of the filed one and in the same year (see
`_document_date`). The base class does not do this because of one Derwent
Valley paper: an LGAT AGM agenda attached to a council meeting, whose title
names the AGM's date. Nothing like it was found on these councils.

The title is not always right either. Of the papers it moved on the
recordings of 20 Oct 2026, two moved to the wrong day, checked against
their PDFs: Clare and Gilbert Valleys' Reconciliation Advisory Group agenda
of 30 November 2021, titled "20 November 2021", and Naracoorte Lucindale's
Audit Committee papers of 16 February 2021, titled with the 12th, the day
the notice was issued. In both the uploaded file's name gave the true date
("...meeting-30-November-21.pdf", "06-Audit-Committee-Minutes-16-February-
2021.pdf"). So the file name breaks the tie: when it agrees with the filed
date, the filed date stands; and an agenda-only and a minutes-only meeting
whose file names agree on a date are joined on it (`_rejoin_by_file_date`).

Three more date rules follow from these collections:

- A paper whose title and file name both give a full date in another year
  than the one it is filed under is a stray from that year, and is dropped,
  unless it is only a typo for the year (see `_drop_strays`). Renmark
  Paringa filed its 28 May 2019 agenda ("OCM-Agenda-28-May-19-public-
  copy.pdf") under 28 May 2020, a Thursday, where it became a council
  meeting that never happened. A title that gives another year alone is a
  typo and is ignored, as Naracoorte Lucindale's 25 February 2025 agenda
  titled "2024.02.25" (file name "2025.02.25-...").
- Minutes titled "Adjourned to <date>" are the adjourned sitting's, and go to
  that date: Clare and Gilbert Valleys' "20 May 2026 Ordinary Council
  Meeting Minutes - Adjourned to 25 May 2026".
- 1 January keeps the base class's handling (the title's date, or dropped).

**Two sittings on one day.** Berri Barmera held its ordinary meeting and a
special budget meeting on 26 April 2022. The special meeting's agenda is
titled "Special Meeting of Council - Third Budget", with no "agenda" in it,
so the base class saw only one agenda, kept one meeting, and paired the
ordinary agenda with the special minutes. Clean minutes of two kinds of
sitting are as sure a sign of two meetings as clean agendas are, so those
groups are split too (see `_split_by_minutes`). Two sittings of the *same*
kind with numbered minutes—Grant's two special meetings of 27 January 2022,
Berri Barmera's of 1 June 2021—are paired by the agendas' start times (see
`_pair_numbered_sittings`).

**Revised papers.** Loxton Waikerie published a "V2 Council Meeting Agenda
- 19 November 2025" beside the original; the base class takes the lower
asset id, the original. A paper marked as a later version of a sibling with
the same title wins (see `_prefer_later_versions`).

**Bodies whose listing stopped.** A council's planning body is often on a
listing of its own, and some of those listings stopped when the body was
replaced (Grant's Council Assessment Panel gave way to the regional panel in
2022). Reading one every night costs a listing page and a 20 s crawl delay
for nothing. `historic_listings` names each with the last year it holds, and
it is read only by a run that wants that year or an earlier one: a full
history run, never production's current year.

**A lost council listing fails the council.** The base class carries on
when one of several listings fails, and raises only when all of them do.
Here the first listing is the council's own meetings and the others are a
planning panel or a stopped listing, so a run that lost the first would
report success with only the panel's meetings. It raises instead, without
reading the rest (see `_listing_documents`). A lost panel listing is still
only a warning, as in the base class.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional

from aus_council_scrapers.lgasa import (
    _MONTHS,
    LGASAFunnelbackScraper,
    _best,
    _Document,
    _Listed,
    _Meeting,
    _sitting,
    _title_date,
    _words,
)

# The titles of workshop, briefing-session and informal-gathering papers.
# Word-bounded so "Budget Workshop" and "Special Briefings Session of
# Council" match. "Information Gathering" and "Informal Meeting of Council"
# are Berri Barmera's other names for the same thing.
INFORMAL_TITLES = re.compile(
    r"\bworkshops?\b|\bbriefings?\b|\binform(?:al|ation)\s+"
    r"(?:gathering|meeting|session)",
    re.IGNORECASE,
)

# A confidential paper, released after the meeting.
CONFIDENTIAL_TITLES = re.compile(r"confidential|\breleas", re.IGNORECASE)

# How far a title's date may be from the filed one and still be trusted
# over it. The worst misfilings seen are a month out (Loxton Waikerie's
# 19 November 2021 agenda filed under 19 October); further than this, the
# title is more likely naming some other meeting.
TITLE_DATE_WINDOW_DAYS = 45

# How far apart an agenda-only and a minutes-only meeting may be filed and
# still be joined on their file names' date; see `_rejoin_by_file_date`.
FILE_DATE_REJOIN_DAYS = 14

# "2022-03-22 Council Minutes", "2026.09.22 Council Agenda": Naracoorte
# Lucindale's titles, which the base class's title dates do not read.
_ISO_TITLE_DATE = re.compile(r"\b(20\d\d)[-.](\d\d)[-.](\d\d)\b")

# "28-May-19", "30-November-21": file names with a two-digit year. Matched
# only after the four-digit forms, on the name with its separators turned
# into spaces.
_SHORT_YEAR_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\s+(\d\d)\b", re.IGNORECASE
)

# "Minutes - Adjourned to 25 May 2026".
_ADJOURNED_TO = re.compile(r"\badjourned\s+to\s+(.*)", re.IGNORECASE)


def _stated_date(title: str) -> Optional[datetime.date]:
    """The full date a title states, in any of the forms these councils use."""
    match = _ISO_TITLE_DATE.search(title)
    if match:
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return _title_date(title)


def _file_date(filename: str) -> Optional[datetime.date]:
    """The full date an uploaded file's name states, if it states one.

    The name as uploaded first ("2021.08.17-Audit-Committee-Minutes.pdf",
    "Audit-Committee-Minutes-14.12.2021.pdf", "16-February-2021"), then with
    its separators as spaces, so "Minutes-_25-June-2024" and a two-digit
    year ("OCM-Agenda-28-May-19-public-copy.pdf") are read too.
    """
    if not filename:
        return None
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stated = _stated_date(stem)
    if stated is not None:
        return stated
    spaced = _words(stem)
    stated = _title_date(spaced)
    if stated is not None:
        return stated
    match = _SHORT_YEAR_DATE.search(spaced)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.datetime.strptime(
            f"{day} {month[:3]} 20{year}", "%d %b %Y"
        ).date()
    except ValueError:
        return None


def _split_by_minutes(meeting: _Meeting) -> list[_Meeting]:
    """Separate two sittings whose clean minutes are of different kinds.

    The base class's `_split_sittings` does this when it finds clean agendas
    of two kinds; this does the same for minutes when the agendas did not
    show it. Every document goes to the sitting its own title names, so an
    agenda titled only "Special Meeting of Council - Third Budget" (an
    unnamed document) joins the special minutes.
    """
    agenda_kinds = {_sitting(d.title) for d in meeting.agendas if d.rank == 0}
    minutes_kinds = {_sitting(d.title) for d in meeting.minutes if d.rank == 0}
    papers_kinds = agenda_kinds | {_sitting(d.title) for d in meeting.unnamed}
    # Each sitting the minutes name must also have an agenda, or a paper
    # titled only with the meeting, and every clean agenda must belong to
    # one of those sittings. Otherwise a minutes title that just omits the
    # kind would be split off as a meeting of its own: Grant's "24 June 2026
    # Minutes", beside "24 June 2026 Special Meeting Minutes" for the one
    # special meeting that day, or its two special meetings of 27 January
    # 2022, whose minutes say only "(First Meeting)" and "(Second Meeting)".
    if (
        len(agenda_kinds) >= 2
        or len(minutes_kinds) < 2
        or not agenda_kinds <= minutes_kinds <= papers_kinds
    ):
        return [meeting]

    parts: dict[str, _Meeting] = {}
    for kind in ("agendas", "minutes", "unnamed"):
        for document in getattr(meeting, kind):
            sitting = _sitting(document.title)
            part = parts.setdefault(
                sitting, _Meeting(meeting.body, meeting.date, sitting=sitting)
            )
            getattr(part, kind).append(document)
    return list(parts.values())


# "5.30PM", "6.30", "(7:00pm)" in an agenda's title or file name: its start
# time. Not part of a dotted date ("14.12.2021", "2023.04.13").
_START_TIME = re.compile(
    r"(?<![\d.])(\d{1,2})[.:](\d{2})(?![\d.])\s*(pm|am)?", re.IGNORECASE
)

# Which of two same-day sittings a minutes title says it is: Grant's
# "(First Meeting)" / "(Second Meeting)", Berri Barmera's "(1)" / "(2)".
_FIRST_OR_SECOND = re.compile(
    r"\b(first|second)\s+meeting\b|\((1|2)\)\s*$", re.IGNORECASE
)


def _ordinal(title: str) -> Optional[int]:
    match = _FIRST_OR_SECOND.search(title)
    if not match:
        return None
    word, digit = match.groups()
    if digit:
        return int(digit)
    return 1 if word.lower() == "first" else 2


def _start_time(text: str) -> Optional[tuple[int, int, str]]:
    """The one start time `text` states: (hour, minute, "am"/"pm"/"")."""
    times = _START_TIME.findall(text)
    if len(times) != 1:
        return None
    hour, minute, half = times[0]
    return int(hour), int(minute), half.lower()


def _clock_order(starts: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """Start times as sortable (hour, minute).

    On a 24 h clock only when every time says am or pm. Grant wrote one
    agenda's time as "5.30PM" and the other's as "6.30"; read as 17:30 and
    6:30, the evening sittings would sort the wrong way round.
    """
    if all(half for _, _, half in starts):
        return [
            (hour + 12 if half == "pm" and hour < 12 else hour, minute)
            for hour, minute, half in starts
        ]
    return [(hour, minute) for hour, minute, _ in starts]


def _pair_numbered_sittings(meeting: _Meeting, filenames: dict) -> list[_Meeting]:
    """Split two same-day sittings of one kind by their numbered minutes.

    Grant held two special meetings on 27 January 2022, at 5.30 pm and
    6.30 pm, with identically titled agendas whose file names give the start
    times, and minutes titled "(First Meeting)" and "(Second Meeting)". Berri
    Barmera held two on 1 June 2021, at 5.30 pm and 7 pm: "Agenda 1 June
    2021" and "Agenda 1 June 2021 (7:00pm)", minutes "(1)" and "(2)". The
    base class keeps one meeting of each day and pairs whichever papers it
    ranks first; on Grant that was the 6.30 pm agenda with the 5.30 pm
    minutes.

    Only when the group holds exactly two clean agendas and its minutes
    include exactly one first and one second, every clean one of them
    numbered. The earlier agenda goes with the first minutes. When both
    agendas state a start time, those decide. When only one does, it is
    taken as the later sitting if it was also uploaded after the other (a
    higher asset id): the time is there to set the added sitting apart from
    the one at the usual hour. On Berri Barmera that pairing is the one the
    four PDFs give. Anything else is left as the base class grouped it.
    """
    agendas = [d for d in meeting.agendas if d.rank == 0]
    numbered = [d for d in meeting.minutes if _ordinal(d.title)]
    if len(agendas) != 2 or len(numbered) != 2:
        return [meeting]
    if {_ordinal(d.title) for d in numbered} != {1, 2}:
        return [meeting]
    if any(d.rank == 0 and d not in numbered for d in meeting.minutes):
        return [meeting]

    starts = [
        _start_time(f"{a.title} {filenames.get(a.asset_id, '')}") for a in agendas
    ]
    if all(starts):
        clock = _clock_order(starts)
        if clock[0] == clock[1]:
            return [meeting]
        ordered = [a for _, a in sorted(zip(clock, agendas), key=lambda p: p[0])]
    elif any(starts):
        timed = agendas[0] if starts[0] else agendas[1]
        untimed = agendas[1] if starts[0] else agendas[0]
        if int(timed.asset_id) < int(untimed.asset_id):
            return [meeting]
        ordered = [untimed, timed]
    else:
        return [meeting]

    minutes = sorted(numbered, key=lambda d: _ordinal(d.title))
    return [
        _Meeting(
            meeting.body, meeting.date, [agenda], [minute], sitting=meeting.sitting
        )
        for agenda, minute in zip(ordered, minutes)
    ]


# "V2 Council Meeting Agenda", "...-Agenda-V2-21-May-2025.pdf",
# "...-Version-2.pdf", "...-v5-Public.pdf".
_VERSION = re.compile(r"(?<![a-z])v(?:ersion)?\s?(\d{1,2})(?!\d)", re.IGNORECASE)


def _version(document: _Document, filename: str) -> int:
    """The version a paper's title or file name marks, 0 when unmarked."""
    found = _VERSION.findall(f"{document.title} {_words(filename)}")
    return max((int(v) for v in found), default=0)


def _unversioned_title(title: str) -> str:
    return " ".join(_VERSION.sub(" ", title).lower().split())


def _prefer_later_versions(meeting: _Meeting, filenames: dict) -> None:
    """Rank a paper behind a later version of itself.

    Only between papers of one kind and one rank whose titles are the same
    once a version mark is taken out, so a revision never displaces another
    sitting's paper filed the same day.
    """
    for documents in (meeting.agendas, meeting.minutes):
        for document in documents:
            mine = _version(document, filenames.get(document.asset_id, ""))
            if any(
                other is not document
                and other.rank == document.rank
                and _unversioned_title(other.title)
                == _unversioned_title(document.title)
                and _version(other, filenames.get(other.asset_id, "")) > mine
                for other in documents
            ):
                document.rank += 1


def _rejoin_by_file_date(meetings: list[_Meeting], filenames: dict) -> list[_Meeting]:
    """Join an agenda-only and a minutes-only meeting on their file names' date.

    Naracoorte Lucindale's Audit Committee meeting of 16 February 2021: the
    agenda is filed under the 16th, the minutes under the 12th, and both are
    titled with the 12th, the day the notice went out. Both file names say
    "16-February-2021", and so do both PDFs. The base class's
    `_rejoin_misdated` would join them on the titles' date, so this runs
    before it: an agenda-only and a minutes-only meeting of one body no more than
    `FILE_DATE_REJOIN_DAYS` apart are joined when their best papers' file
    names state the same date and it is one of the two filed dates; the
    joined meeting takes that date.
    """

    def file_date(documents: list[_Document]) -> Optional[datetime.date]:
        best = _best(documents)
        return _file_date(filenames.get(best.asset_id, "")) if best else None

    agenda_only = [m for m in meetings if m.agendas and not m.minutes and not m.unnamed]
    minutes_only = [
        m for m in meetings if m.minutes and not m.agendas and not m.unnamed
    ]
    joined: set[int] = set()
    for agenda_meeting in agenda_only:
        stated = file_date(agenda_meeting.agendas)
        if stated is None:
            continue
        for minutes_meeting in minutes_only:
            if id(minutes_meeting) in joined or (
                minutes_meeting.body != agenda_meeting.body
                or minutes_meeting.sitting != agenda_meeting.sitting
            ):
                continue
            filed = {
                datetime.date.fromisoformat(agenda_meeting.date),
                datetime.date.fromisoformat(minutes_meeting.date),
            }
            if (
                file_date(minutes_meeting.minutes) != stated
                or stated not in filed
                or (max(filed) - min(filed)).days > FILE_DATE_REJOIN_DAYS
            ):
                continue
            agenda_meeting.minutes = minutes_meeting.minutes
            agenda_meeting.date = stated.isoformat()
            joined.add(id(minutes_meeting))
            break
    return [m for m in meetings if id(m) not in joined]


def _other_year(title: str, year: int) -> bool:
    stated = _stated_date(title)
    return stated is not None and stated.year != year


def _other_year_file(filename: str, year: int) -> bool:
    stated = _file_date(filename)
    return stated is not None and stated.year != year


def _drop_strays(meetings: list[_Meeting], strays: set[str]) -> list[_Meeting]:
    """Drop the papers of another year, unless they are only misdated.

    `strays` are the papers whose title and file name both give a full date
    in another year than the one they are filed under. Renmark Paringa's
    28 May 2019 agenda ("OCM-Agenda-28-May-19-public-copy.pdf"), filed under
    28 May 2020, a Thursday, became a council meeting that never happened;
    the real one that week was on Tuesday the 26th. But Loxton Waikerie's
    minutes of 21 January 2021 are titled and named "21 January 2020" (the
    PDF says 2021), and are filed beside that meeting's agenda.

    So a stray is kept only when it is a typo for the year: its day and
    month are the meeting's, and another paper of that meeting states the
    meeting's full date. A meeting left with no papers is dropped.
    """
    kept = []
    for meeting in meetings:
        papers = meeting.agendas + meeting.minutes + meeting.unnamed
        confirmed = any(
            d.asset_id not in strays
            and _stated_date(d.title) == datetime.date.fromisoformat(meeting.date)
            for d in papers
        )
        day = meeting.date[5:]

        def keep(document: _Document) -> bool:
            if document.asset_id not in strays:
                return True
            stated = _stated_date(document.title)
            return confirmed and stated.isoformat()[5:] == day

        meeting.agendas = [d for d in meeting.agendas if keep(d)]
        meeting.minutes = [d for d in meeting.minutes if keep(d)]
        meeting.unnamed = [d for d in meeting.unnamed if keep(d)]
        if meeting.agendas or meeting.minutes or meeting.unnamed:
            kept.append(meeting)
    return kept


class RegionalLGASAScraper(LGASAFunnelbackScraper):
    """An `LGASAFunnelbackScraper` with the additions above."""

    # Documents whose title matches are dropped before grouping. None keeps
    # every document, as the base class does.
    skip_titles: Optional[re.Pattern] = None

    # (listing URL, last year it holds documents for). Read after
    # `listing_urls`, and only when a wanted year is that year or earlier.
    historic_listings: tuple[tuple[str, int], ...] = ()

    def scraper(self):
        earliest = min(self._wanted_years())
        historic = tuple(
            url for url, last_year in self.historic_listings if earliest <= last_year
        )
        # An instance attribute, built afresh from the class's on every run,
        # so a second run with other years does not inherit the first's list.
        self.listing_urls = type(self).listing_urls + historic
        self._council_listing_error: Optional[Exception] = None
        records = super().scraper()
        if self._council_listing_error is not None:
            raise RuntimeError(
                f"{self.council_name}: could not read the council's own "
                f"listing, {self.listing_urls[0]}: "
                f"{type(self._council_listing_error).__name__}: "
                f"{self._council_listing_error}"
            ) from self._council_listing_error
        return records

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        """The base class's read, with the council's own listing required.

        The base class catches a failed listing and moves on to the next.
        When the first listing, the council's own meetings, has failed, the
        rest are not read (each would cost a page and a crawl delay for a run
        that is going to fail) and `scraper` raises.
        """
        if self._council_listing_error is not None:
            return []
        try:
            return super()._listing_documents(listing_url, earliest_year)
        except Exception as error:
            if listing_url == self.listing_urls[0]:
                self._council_listing_error = error
            raise

    def _skipped(self, listed: _Listed) -> bool:
        """Whether a listed document is dropped before grouping."""
        return self.skip_titles is not None and bool(
            self.skip_titles.search(listed.title)
        )

    def _relabel(self, listed: _Listed, year: int) -> _Listed:
        """A listed document with its committee label corrected, if needed.

        For a council that files one body's papers under two labels; the
        default changes nothing.
        """
        return listed

    def _document_date(self, listed: _Listed, year: int) -> Optional[str]:
        """The date to group a listed document under, or None to drop it.

        See the module docstring for each rule and the papers behind it.
        """
        filed = listed.date
        title = listed.title
        if filed.endswith("-01-01"):
            stated = _stated_date(title)
            if stated and stated.year == year and (stated.month, stated.day) != (1, 1):
                return stated.isoformat()
            return None
        filed_day = datetime.date.fromisoformat(filed)

        adjourned = _ADJOURNED_TO.search(title)
        if adjourned:
            to = _stated_date(adjourned.group(1))
            if (
                to is not None
                and to.year == year
                and 0 < (to - filed_day).days <= TITLE_DATE_WINDOW_DAYS
            ):
                return to.isoformat()

        stated = _stated_date(title)
        if stated is None or stated.year != year:
            # Another year in the title is a typo or a stray; see
            # `_drop_strays`, which decides which.
            return filed
        file_date = _file_date(listed.filename)
        if abs((stated - filed_day).days) > TITLE_DATE_WINDOW_DAYS:
            return filed
        if stated != filed_day and file_date == filed_day:
            return filed
        return stated.isoformat()

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        # `_assemble` has already settled each document's date with
        # `_document_date`, which sees the file name as well as the title.
        return filed

    def _assemble(self, documents: list[_Listed], year: int) -> list[_Meeting]:
        filenames = {d.asset_id: d.filename for d in documents}
        settled = []
        for listed in documents:
            if self._skipped(listed) or listed.date is None:
                continue
            listed = self._relabel(listed, year)
            date = self._document_date(listed, year)
            if date is not None:
                settled.append(dataclasses.replace(listed, date=date))

        strays = {
            listed.asset_id
            for listed in settled
            if _other_year(listed.title, year)
            and _other_year_file(listed.filename, year)
        }
        meetings = _drop_strays(super()._assemble(settled, year), strays)
        meetings = _rejoin_by_file_date(meetings, filenames)
        parts = [
            numbered
            for meeting in meetings
            for part in _split_by_minutes(meeting)
            for numbered in _pair_numbered_sittings(part, filenames)
        ]
        for part in parts:
            _prefer_later_versions(part, filenames)
        return parts
