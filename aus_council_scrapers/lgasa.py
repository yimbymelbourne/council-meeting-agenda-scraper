"""Councils on the LGA SA shared Squiz Matrix platform.

The Local Government Association of South Australia hosts dozens of council
websites on one Squiz Matrix install (`lgasa-web.squiz.cloud`), and each of
those councils publishes its agendas and minutes into a Funnelback "push"
collection named `<council>-council-minutes-and-agenda-push`. The council's
own "agendas and minutes" page is a server-side rendering of that collection:
one `li.result-item` per document, newest meeting date first, each carrying
the document's title, its `/__data/assets/<type>/<dir>/<assetId>/<file>`
URL, the committee it was filed under and its meeting date.

Derwent Valley in Tasmania is hosted on the same platform and publishes into
the same shape of collection, which is why a TAS council lives here too.

**robots.txt.** All ten council hosts read here—the seven
`LGASAFunnelbackScraper` councils', and Charles Sturt's, Tea Tree Gully's
and Mount Barker's, whose older papers `ResolveWithLGASAArchive` reads—served
byte-identical robots.txt files when checked on 19 Oct 2026 (the Matrix
default). The lines that bind this scraper:

    User-agent: *
    Crawl-delay: 20
    # Prevent crawling search pages
    Disallow: /search
    # Prevent crawling of Funnelback search queries or facets.
    Disallow: *?*query=
    Disallow: *?*f.*%7C*=

The rest disallow Matrix internals (`/_designs/`, `/*?sq_content_src=`,
`/*_recache`, `/*_edit`, `/*_admin`, `/*_login`, `/*_performance`,
`/*_design`, `/*_web_services`, `/__lib`, `/__fudge`). The JSON API this
module first used, `lgasa-search.lga.sa.gov.au/s/search.json`, is disallowed
by that host's own robots.txt (`Disallow: /s/`), so it is not used.
`lgasa-web.squiz.cloud` has no robots.txt (404).

So this module reads only the councils' listing pages, at their own paths,
with two parameters added: `num_ranks` (page size) and `start_rank` (the
pager). Neither matches a Disallow line. The site's own pager links also add
`collection=` and `query=!FunDoesNotExist:PadreNull`; `query=` is the
disallowed part, and the page renders the same collection (and, on a
committee page, the same committee filter) without either. No facet (`f.*|*`)
parameter is ever sent, so there is no year filter: the listing is read
newest first, and a run wanting only recent years stops paging once it is
past them (see `NEWEST_UNSORTED_YEAR`). Requests to one host are spaced
`CRAWL_DELAY_SECONDS` apart through `fetcher.sleep`, which replay turns into
a no-op.

**One result is one document, not one meeting.** Meetings are rebuilt by
grouping documents on the body that met (the committee label, normalised by
`_body_name`) and the meeting date, then choosing the agenda and the minutes
from the group (see `_classify`). The listing does not show the document
category (`maaCategory`) the JSON carried, and the category was wrong often
enough that the title already decided most documents. Where the title names
neither agenda nor minutes, the uploaded file name usually does
("12-10-2026-GBEDC-Agenda.PDF"), so it is read next; after that, a notice of
meeting is an agenda, "Notes" are minutes, and a document titled only with
its meeting fills whichever of the two that meeting lacks (`_fill`). On the
recordings of 19 Oct 2026 this reproduces the JSON-based output exactly for
Port Adelaide Enfield, Prospect, Campbelltown and Derwent Valley.

**Cloudflare.** From GitHub's runners the council domains answer a Cloudflare
JS challenge (`cf-mitigated: challenge`) to any requests client, whatever its
User-Agent. Headless Chrome is challenged too, while Chrome with the
"HeadlessChrome" token stripped clears it in a few seconds. So the listing
is fetched through Selenium with `strip_headless_user_agent`.

**Document URLs.** Every asset is also served by the Matrix origin itself,
`lgasa-web.squiz.cloud/?a=<assetId>` (`server: openresty`, no Cloudflare),
which answers a plain client with the PDF. The council-domain URL in the
listing sits behind the council's Cloudflare zone, which challenges the
runners, so a PDF summariser running there could not read it. The origin URL
is what we emit—see `DOCUMENT_ROOT`.

**Cost.** `PAGE_SIZE` documents per request. The first 500 reach back before
1 January on every listing here (Campbelltown, the busiest, filed 246
documents in 2025, a third of them audio), so production, which asks for the
current year only, pays one request per listing page and no crawl delay.
Light Regional has no whole-collection page, so it reads two committee pages
and pays one 20 s delay. A full-history run reads every page: 2 to 7 per
listing, 20 s apart.
"""

from __future__ import annotations

import datetime
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper, SoleSourceFailed

# The Matrix origin every LGA SA council site is served from. `?a=<assetId>`
# answers with the document itself—no redirect, no challenge—and asset ids
# are global to the install, so one root serves every council's documents.
DOCUMENT_ROOT = "https://lgasa-web.squiz.cloud"

# `Crawl-delay: 20` in every council's robots.txt.
CRAWL_DELAY_SECONDS = 20

# Documents per listing request. The page's own "Limit" menu offers 10, 20
# and 50; at 50, reading Gawler's 3,298 documents would be 66 requests 20 s
# apart. 500 keeps production to one request per listing and a full
# recording to a handful, and is fewer requests to the council's server than
# any smaller size, which is what the crawl delay is protecting.
PAGE_SIZE = 500

# Gawler, the largest listing, is 7 pages of 500. The cap only stops a
# listing that never runs out from paging forever.
MAX_PAGES = 20

# The listing is newest meeting date first only for the documents that carry
# Funnelback's sort date. Older uploads without one come after all of them,
# in no date order: on Port Adelaide Enfield the sorted run reaches 2019 by
# rank 500, and 2020-21 council agendas turn up again at ranks 778-989. So a
# run can stop paging early only when every wanted year is newer than the
# newest document in any listing's unsorted tail, measured on the recordings
# of 19 Oct 2026 (see `_listing_documents`). Otherwise it reads the whole
# listing.
NEWEST_UNSORTED_YEAR = 2021

# A Cloudflare challenge clears in 6-9 s from a runner. Give it headroom, but
# not so much that a council whose challenge never clears holds a worker for
# long: with the one retry in `_fetch_page`, a challenge that never clears
# costs about 45 s per listing page (two 20 s waits and two Chrome starts) of
# the shared 600 s budget; the crawl delay before the retry has already run
# out by then.
CHALLENGE_WAIT_SECONDS = 20

# The element that holds the result list; a challenge page does not have it.
_LISTING_SELECTOR = ".minutes-and-agendas-listing"

# Word boundaries treat "_" as a word character, so file names
# ("Council_Agenda_Final.pdf") are matched with the separators turned into
# spaces first; see `_words`.
_AGENDA_WORD = re.compile(r"\bagendas?\b", re.IGNORECASE)
_MINUTES_WORD = re.compile(r"\bminutes?\b", re.IGNORECASE)

# A title matching this is not the meeting's agenda or minutes even when it is
# filed as one: a cancellation or rescheduling notice, a late or
# supplementary report, or a recording.
#
# "Rescheduled" and "released" alone are *not* here. Councils use both on the
# full document—Port Adelaide Enfield's "2 March 2023 Agenda for Rescheduled
# Audit and Risk Committee Meeting", and its 11 July 2023 council agenda and
# minutes, re-uploaded whole as "... - Released" once the confidential items
# were. Excluding them lost that meeting outright. Only a *notice* of
# rescheduling ("Notice - Rescheduling of CAP Meeting ...") is excluded; the
# words themselves are `_WEAKER` marks, so a clean sibling still wins.
_EXCLUDE = re.compile(
    r"cancel|postpone|notice\W+(?:of\W+)?reschedul|\blate\b|supplementary|"
    r"addendum|audio|recording",
    re.IGNORECASE,
)

# What *is* never the agenda or minutes is one confidential item released on
# its own: "Confidential Council Agenda - ... - Item 9.1 - Released", Gawler's
# "...-Council-Minutes-Confidential-item-19.2-...-released-15-02-2023.PDF".
# Those name the item; a whole re-released document does not.
_RELEASED = re.compile(r"releas", re.IGNORECASE)
_NAMES_ITEM = re.compile(r"\bit(?:e)?ms?\b[-\s]*\d", re.IGNORECASE)

# Attachments are filed beside the agenda—"28 May 2026 - Council Agenda
# Attachments", "Attachments1-3 Agenda Item 9.11"—and are never it. The
# exception is an agenda published with its attachments in one file
# ("Council Agenda & Attachments", "Agenda including Attachment 2"), which is
# the agenda, and is kept as a weaker candidate.
_ATTACHMENT = re.compile(r"attachment", re.IGNORECASE)
_AGENDA_WITH_ATTACHMENTS = re.compile(
    r"agenda\s*(?:and|&|with|including|plus)\s*(?:the\s*)?attachment",
    re.IGNORECASE,
)

# Marks of a document that may be the agenda or minutes but is less likely to
# be the main one than a sibling without them: a single agenda item, an
# attachment, a confidential or re-released version, part 2 of several, a
# notice of meeting filed beside the agenda, a slide deck.
#
# "Notice" counts only as a notice of meeting, not as the phrase "Motions on
# Notice" or "Questions with Notice". Gawler's "15-03-2022 Council Agenda
# Special Motions on Notice.PDF" is a whole agenda, and demoting it paired the
# other special meeting's agenda with this one's minutes.
_WEAKER = (
    # "Item 9.1", and "Agenda-Item-10.8" in a title that is a file name.
    re.compile(r"\bitems?[\s_-]*\d", re.IGNORECASE),
    re.compile(r"attachment", re.IGNORECASE),
    re.compile(r"confidential", re.IGNORECASE),
    re.compile(r"\bpart\s*[2-9]\b", re.IGNORECASE),
    re.compile(r"\breports?\b", re.IGNORECASE),
    re.compile(r"(?<!\bon )(?<!\bwith )\bnotice\b", re.IGNORECASE),
    re.compile(r"releas|reschedul", re.IGNORECASE),
    re.compile(
        r"presentation|additional information|amended|separate cover", re.IGNORECASE
    ),
)

# A notice of meeting is issued with, and often is, the agenda: Gawler's
# "14-02-2022 IES Notice of meeting.pdf", Walkerville's "Audit Committee
# Special Meeting Notice 19 February 2021". Only a notice of a *meeting*:
# Light files "Notice of Information Session" under Council Meetings, and
# those sessions are not council meetings.
_MEETING_NOTICE = re.compile(
    r"\bnotice of (?:[\w&]+ ){0,3}meeting\b|\bmeeting notice\b", re.IGNORECASE
)

_NOTICE_WORD = re.compile(r"\bnotice\b", re.IGNORECASE)

# Workshop and advisory-group "Notes" are those sittings' minutes (Prospect's
# "Councillor Information & Workshop Session - Notes - 4 February 2020").
_NOTES = re.compile(r"\bnotes\b", re.IGNORECASE)

# A title naming neither kind is used only when it names a sitting: "11 June
# 2024 - Ordinary Council Meeting", "Information/Briefing Session 22 Jan
# 2024", "Informal Gathering 1 March 2021". Terms of reference, annual
# reports and InfoDocs name none.
_SITTING_WORDS = re.compile(
    r"\b(?:meeting|session|gathering|workshop)\b", re.IGNORECASE
)

# File-name abbreviations: Light's "OCM20260922AGN.pdf" and
# "OCM20260922MIN222.PDF", Gawler's "CAP_20200721_AGN_2347.pdf". Bounded by
# anything but a letter, so "admin" is not minutes.
_FILE_AGENDA = re.compile(r"(?<![a-z])agn(?![a-z])", re.IGNORECASE)
_FILE_MINUTES = re.compile(r"(?<![a-z])min(?![a-z])", re.IGNORECASE)

_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_AGM = re.compile(r"\bannual general meeting\b|\bAGM\b", re.IGNORECASE)
_SECOND = re.compile(r"\bsecond\b", re.IGNORECASE)


def _sitting(title: str) -> str:
    """Which kind of sitting a document's title says it belongs to.

    "Second" marks a second sitting of the same kind that day: Gawler held
    a special meeting and a "Second Special Council Meeting" on 15 February
    2024, and only the word tells their documents apart.
    """
    if _AGM.search(title):
        kind = "agm"
    elif _SPECIAL.search(title):
        kind = "special"
    else:
        kind = "ordinary"
    return f"second {kind}" if _SECOND.search(title) else kind


COUNCIL_MEETING = "Council Meeting"

_MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|"
    "march|april|june|july|august|september|october|november|december"
)

# A title that names a meeting of the full council. It outranks the committee
# label, which is occasionally just wrong: Port Adelaide Enfield filed its
# 28 January 2025 "Agenda for Ordinary Council Meeting" under "Council
# Assessment Panel", which split that meeting's agenda from its minutes and
# put the agenda on a CAP meeting that never happened.
_COUNCIL_TITLE = re.compile(r"\b(?:ordinary|special) council meeting\b", re.IGNORECASE)

# Committee labels that mean "the council itself". Several councils file their
# council meetings under a label describing the page rather than the body—
# Port Adelaide Enfield's recent ones are under "Agendas and minutes".
_COUNCIL_LABELS = {
    "",
    "council",
    "council meeting",
    "council meetings",
    "full council",
    "agendas and minutes",
    "agendas & minutes",
    "agenda and minutes",
    "council agenda and minutes",
    "council agendas and minutes",
}
_PAGE_SUFFIX = re.compile(r"\s*agendas?\s*(?:and|&)\s*minutes\s*$", re.IGNORECASE)


@dataclass
class _Document:
    asset_id: str
    title: str
    # Lower is a better candidate; see `_classify`.
    rank: int
    # The listed file name's extension, lower-cased ("" when the listing
    # gives no file name).
    file_type: str = "pdf"


@dataclass
class _Listed:
    """One `li.result-item` from a listing page."""

    asset_id: str
    title: str
    # The uploaded file's name, from the end of its `/__data/assets/` URL.
    filename: str
    # "pdf_file", "file", "audio_file", "word_doc", ...: Matrix's asset type,
    # the path segment after `/__data/assets/`.
    asset_type: str
    committee: str
    # ISO date, or None when the listing shows none or one that will not parse.
    date: Optional[str]


@dataclass
class _Meeting:
    # The body that met, already turned from a committee label into a
    # meeting type by `LGASAFunnelbackScraper._body_name`.
    body: str
    date: str
    agendas: list[_Document] = field(default_factory=list)
    minutes: list[_Document] = field(default_factory=list)
    # Documents that name neither kind; see `_classify` and `_fill`.
    unnamed: list[_Document] = field(default_factory=list)
    # Set when this is one of several sittings split out of a single
    # committee-and-date group; see `_split_sittings`.
    sitting: Optional[str] = None


def _split_sittings(meeting: _Meeting) -> list[_Meeting]:
    """Separate meetings that share a body and a date.

    A council can hold its ordinary meeting and an AGM or a special meeting on
    the same evening—Derwent Valley did in December 2022, 2023 and 2024,
    Light on 9 December 2025—and they are filed under one committee with one
    date. The
    titles are what tell them apart, but titles are inconsistent within a
    single meeting too: Gawler's "Council Agenda.PDF" pairs with "Council
    Minutes Special.PDF". So the group is split only when it holds two
    *clean* agendas (rank 0) for different kinds of sitting, which a single
    meeting never has; otherwise it stays one meeting.

    Two sittings of the same kind on one day cannot be told apart this way;
    `_pair_by_title_words` handles those it can.
    """
    clean = {_sitting(d.title) for d in meeting.agendas if d.rank == 0}
    if len(clean) < 2:
        return [meeting]

    by_sitting: dict[str, _Meeting] = {}
    for kind in ("agendas", "minutes", "unnamed"):
        for document in getattr(meeting, kind):
            sitting = _sitting(document.title)
            part = by_sitting.setdefault(
                sitting,
                _Meeting(meeting.body, meeting.date, sitting=sitting),
            )
            getattr(part, kind).append(document)
    return list(by_sitting.values())


# Words every title of a meeting may carry, so sharing one says nothing about
# which meeting two documents belong to.
_GENERIC_WORDS = frozenset(
    "agenda agendas minutes minute council meeting meetings special ordinary "
    "the of and for on to pdf public unconfirmed confirmed".split()
) | frozenset(_MONTHS.split("|"))


def _distinct_words(title: str) -> set[str]:
    return set(re.findall(r"[a-z]+", title.lower())) - _GENERIC_WORDS


def _pair_by_title_words(meeting: _Meeting) -> list[_Meeting]:
    """Separate two same-kind sittings whose documents name their business.

    Gawler held two special meetings on 15 March 2022, filed as "Council
    Agenda Special Budget", "Council Agenda Special Motions on Notice",
    "Special Council Minutes - Budget" and "Special Council Minutes -
    Heritage CAP". Choosing one agenda and one minutes from that group paired
    one meeting's agenda with the other's minutes. When a group holds exactly
    two clean agendas and two clean minutes, and exactly one agenda/minutes
    pair shares a word beyond the generic ones ("Budget"), that pair is one
    meeting and the other two documents are the second.

    Identical titles (Walkerville's two "Special Council Agenda 29 September
    2025") share nothing distinctive, so they stay one meeting.
    """
    agendas = [d for d in meeting.agendas if d.rank == 0]
    minutes = [d for d in meeting.minutes if d.rank == 0]
    if len(agendas) != 2 or len(minutes) != 2:
        return [meeting]
    shared = [
        (a, m)
        for a in agendas
        for m in minutes
        if _distinct_words(a.title) & _distinct_words(m.title)
    ]
    if len(shared) != 1:
        return [meeting]
    agenda, minute = shared[0]
    other_agenda = next(d for d in agendas if d is not agenda)
    other_minute = next(d for d in minutes if d is not minute)
    return [
        _Meeting(
            meeting.body, meeting.date, [agenda], [minute], sitting=meeting.sitting
        ),
        _Meeting(
            meeting.body,
            meeting.date,
            [other_agenda],
            [other_minute],
            sitting=meeting.sitting,
        ),
    ]


@dataclass
class _Chosen:
    """One meeting with its agenda and minutes picked."""

    name: str
    date: str
    agenda: Optional[_Document]
    minutes: Optional[_Document]


# Hyphens as well as spaces: some titles are the uploaded filename
# ("22-July-2020-AGM-Agenda.pdf").
_TITLE_DATE_WORDS = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+({_MONTHS})\.?,?[\s-]+(\d{{4}})\b",
    re.IGNORECASE,
)
_TITLE_DATE_DIGITS = re.compile(r"\b(\d{1,2})[-./](\d{1,2})[-./](\d{4})\b")


def _title_date(title: str) -> Optional[datetime.date]:
    """The meeting date a document's title states, if it states one."""
    match = _TITLE_DATE_WORDS.search(title)
    try:
        if match:
            day, month, year = match.groups()
            return datetime.datetime.strptime(
                f"{day} {month[:3]} {year}", "%d %b %Y"
            ).date()
        match = _TITLE_DATE_DIGITS.search(title)
        if match:
            day, month, year = (int(g) for g in match.groups())
            return datetime.date(year, month, day)
    except ValueError:
        return None
    return None


# How far apart an agenda-only and a minutes-only meeting may be filed and
# still be joined when their titles disagree; see `_rejoin_misdated`. Under a
# week, so two weekly sittings of a body (Prospect's workshop sessions) are
# never mistaken for one meeting.
_NEARBY_DAYS = 5


def _rejoin_misdated(meetings: list[_Chosen]) -> list[_Chosen]:
    """Put an agenda and its minutes back together when one is misdated.

    `docMeetingDate` is typed by hand per document, and in about 1.5% of
    meetings the agenda and the minutes disagree by a few days—Campbelltown
    dated its 21 July 2026 council agenda the 20th, Walkerville dated the
    minutes of its 8 June 2023 special meeting the 13th. Grouping on the date
    then yields an agenda-only meeting beside a minutes-only one.

    Both titles normally still state the real date. So an agenda-only and a
    minutes-only meeting of the same name are joined when their titles give
    the same date, that date is one of the two they were filed under, and
    they are no more than a fortnight apart. The joined meeting takes the date
    the titles agree on.

    Sometimes the titles disagree too. Derwent Valley's minutes of its
    22 August 2024 meeting are filed and titled 26 August, and those of
    25 July 2024 are filed and titled 24 July; the minutes PDFs give 22 August
    and 25 July. So a second pass joins an agenda-only and a minutes-only
    meeting of the same name that are `_NEARBY_DAYS` apart or less, when each
    is the other's only candidate and no other meeting of that name falls
    between them. The agenda's date wins, because an agenda is filed before
    the meeting and its date is the one the council announced.
    """
    agenda_only = [m for m in meetings if m.agenda and not m.minutes]
    minutes_only = [m for m in meetings if m.minutes and not m.agenda]
    joined: set[int] = set()

    for agenda_meeting in agenda_only:
        stated = _title_date(agenda_meeting.agenda.title)
        if stated is None:
            continue
        for minutes_meeting in minutes_only:
            if (
                id(minutes_meeting) in joined
                or minutes_meeting.name != agenda_meeting.name
            ):
                continue
            if _title_date(minutes_meeting.minutes.title) != stated:
                continue
            filed = {
                datetime.date.fromisoformat(agenda_meeting.date),
                datetime.date.fromisoformat(minutes_meeting.date),
            }
            if stated not in filed or (max(filed) - min(filed)).days > 14:
                continue
            agenda_meeting.minutes = minutes_meeting.minutes
            agenda_meeting.date = stated.isoformat()
            joined.add(id(minutes_meeting))
            break

    def day(meeting: _Chosen) -> datetime.date:
        return datetime.date.fromisoformat(meeting.date)

    def candidates(meeting: _Chosen, pool: list[_Chosen]) -> list[_Chosen]:
        return [
            other
            for other in pool
            if id(other) not in joined
            and other.name == meeting.name
            and abs((day(other) - day(meeting)).days) <= _NEARBY_DAYS
        ]

    agenda_only = [m for m in agenda_only if not m.minutes]
    for agenda_meeting in agenda_only:
        nearby = candidates(agenda_meeting, minutes_only)
        if len(nearby) != 1 or len(candidates(nearby[0], agenda_only)) != 1:
            continue
        minutes_meeting = nearby[0]
        low, high = sorted((day(agenda_meeting), day(minutes_meeting)))
        if any(
            other.name == agenda_meeting.name and low < day(other) < high
            for other in meetings
            if other is not agenda_meeting and other is not minutes_meeting
        ):
            continue
        agenda_meeting.minutes = minutes_meeting.minutes
        joined.add(id(minutes_meeting))

    return [m for m in meetings if id(m) not in joined]


def _best(documents: list[_Document]) -> Optional[_Document]:
    """The best candidate: lowest rank, then a readable PDF, then oldest.

    Among equals, one whose listed file is a PDF beats one that is not.
    Light filed "Council Agenda - 28 April 2020" twice: ?a=652051 is a dead
    404 stub, listed with no file at all, and ?a=1100715 the 409 KB agenda;
    the lower asset id alone chose the stub.

    After that, the lowest asset id: the document uploaded first, which on
    these sites is the agenda itself rather than a later report or part.
    """
    if not documents:
        return None
    return min(
        documents,
        key=lambda d: (d.rank, d.file_type != "pdf", int(d.asset_id)),
    )


def _words(name: str) -> str:
    """A file name with its separators turned into spaces, for matching."""
    return re.sub(r"[_\-.+]+", " ", name)


def _not_the_document(text: str) -> bool:
    """True for a notice, a late item, a recording, a released single item or
    an attachment: something filed beside the agenda or minutes, not it."""
    if _EXCLUDE.search(text):
        return True
    if _RELEASED.search(text) and _NAMES_ITEM.search(text):
        return True
    return bool(_ATTACHMENT.search(text) and not _AGENDA_WITH_ATTACHMENTS.search(text))


def _names_kind(text: str, filename: bool = False) -> Optional[str]:
    """The kind ("agenda" or "minutes") when the text names exactly one."""
    says_agenda = bool(_AGENDA_WORD.search(text))
    says_minutes = bool(_MINUTES_WORD.search(text))
    if filename:
        says_agenda = says_agenda or bool(_FILE_AGENDA.search(text))
        says_minutes = says_minutes or bool(_FILE_MINUTES.search(text))
    if says_agenda == says_minutes:
        return None
    return "agenda" if says_agenda else "minutes"


# Rank added for each step further from a title that names its kind.
_FROM_FILENAME = 1
_FROM_NOTICE = 1
_UNNAMED = 2


def _classify(
    title: str, filename: str = "", notices_are_agendas: bool = False
) -> Optional[tuple[str, int]]:
    """Whether a document is an agenda or minutes, and how good a candidate.

    Returns ``(kind, rank)`` or None. A title that names exactly one of
    "agenda" or "minutes" decides the kind. The listing page shows no
    document category, so when the title names both or neither ("12-10-2026 -
    Gawler Business & Economic Development Committee"), the uploaded file
    name decides instead ("12-10-2026-GBEDC-Agenda.PDF"); failing that, a
    notice of meeting is the agenda and "Notes" are the minutes. A clean
    title that names only a sitting ("11 June 2024 - Ordinary Council
    Meeting") is "unnamed", and `_fill` uses it for a meeting missing its
    agenda or its minutes. Each step down ranks behind the one before, and a
    title carrying a `_WEAKER` mark ranks behind one that does not, so a
    weaker candidate is chosen only when nothing better was filed for that
    meeting.
    """
    if _not_the_document(title):
        return None

    rank = sum(1 for pattern in _WEAKER if pattern.search(title))
    kind = _names_kind(title)
    if kind is not None:
        return kind, rank
    name = _words(filename)
    if _not_the_document(name):
        return None
    kind = _names_kind(name, filename=True)
    if kind is not None:
        return kind, rank + _FROM_FILENAME
    if _MEETING_NOTICE.search(title) or _MEETING_NOTICE.search(name):
        return "agenda", rank + _FROM_NOTICE
    if notices_are_agendas and (
        _SITTING_WORDS.search(title) or _NOTICE_WORD.search(f"{title} {name}")
    ):
        # A committee whose documents are all notices of its sessions.
        return "agenda", rank + _UNNAMED
    if _NOTES.search(title):
        return "minutes", rank + _FROM_NOTICE
    weaker_name = any(pattern.search(name) for pattern in _WEAKER)
    if rank == 0 and not weaker_name and _SITTING_WORDS.search(title):
        return "unnamed", _UNNAMED
    return None


def _fill(
    agenda: Optional[_Document],
    minutes: Optional[_Document],
    unnamed: list[_Document],
) -> tuple[Optional[_Document], Optional[_Document]]:
    """Put the best unnamed document in a meeting's empty slot.

    A document whose title and file name name neither kind is, on these
    collections, the meeting's agenda or its minutes filed under a bare
    meeting name. The JSON category used to say which; the listing does not,
    but the meeting's other document does. Port Adelaide Enfield's "11 June
    2024 - Ordinary Council Meeting" sits beside that meeting's minutes, so
    it is the agenda; Gawler's "04-05-2021 Special Council Meeting.pdf" sits
    beside that meeting's agenda, so it is the minutes. Alone, it is taken as
    the agenda, which is published first. A meeting with both already keeps
    them.
    """
    candidate = _best(unnamed)
    if candidate is None or (agenda and minutes):
        return agenda, minutes
    if agenda is None:
        return candidate, minutes
    return agenda, candidate


_ASSET_PATH = re.compile(r"/__data/assets/([^/]+)/[^/]+/(\d+)/([^/?#]*)")
_PUSH_ASSET = re.compile(r"(?:pushAsset%3D|[?&]a%3D|[?&]a=)(\d+)")


def _listing_date(text: str) -> Optional[str]:
    """The listing's "12 Oct 2026" as an ISO date, or None."""
    try:
        return datetime.datetime.strptime(text.strip(), "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def _text(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _parse_listing(page: str) -> tuple[list[_Listed], Optional[int]]:
    """The documents on one listing page, and how many the listing holds.

    The asset id comes from the document's `/__data/assets/` URL. A result
    whose URL is not one (none seen so far) falls back to the `pushAsset` id
    in its click-tracking link.
    """
    soup = BeautifulSoup(page, "html.parser")
    count = re.search(
        r"of\s+([\d,]+)\s+results?",
        _text(soup.select_one(".result-info__results-count")),
    )
    total = int(count.group(1).replace(",", "")) if count else None

    documents = []
    for item in soup.select("li.result-item"):
        url = _text(item.select_one(".result-item__url"))
        path = _ASSET_PATH.search(urllib.parse.unquote(url))
        if path:
            asset_type, asset_id, filename = path.groups()
        else:
            link = item.select_one("a[href]")
            pushed = _PUSH_ASSET.search(link["href"]) if link else None
            if not pushed:
                continue
            asset_type, asset_id, filename = "", pushed.group(1), ""
        documents.append(
            _Listed(
                asset_id=asset_id,
                title=_text(item.select_one(".result-item__heading")),
                filename=filename,
                asset_type=asset_type,
                committee=_text(
                    item.select_one(".minutes-and-agendas-listing__committe")
                ),
                date=_listing_date(
                    _text(item.select_one(".minutes-and-agendas-listing__meetingDate"))
                ),
            )
        )
    return documents, total


class LGASAFunnelbackScraper(BaseScraper):
    """A council whose agendas and minutes page renders an LGA SA collection.

    A subclass supplies the listing page or pages to read, and optionally
    committee names to rename or skip. The first listing page is also the
    `webpage_url` of every meeting.
    """

    # The challenge is only cleared without the "HeadlessChrome" token; see
    # the module docstring.
    strip_headless_user_agent = True

    # The council's own agendas-and-minutes listing pages, bare: no query
    # string. Most councils have one page over the whole collection; a
    # council that only has a page per committee lists each one wanted.
    listing_urls: tuple[str, ...] = ()

    # Committee label -> meeting type, for labels `_body_name` cannot
    # turn into one by itself.
    committee_names: dict[str, str] = {}

    # Committees whose documents the council republishes but whose meetings
    # are not the council's own.
    skip_committees: frozenset[str] = frozenset()

    # Committees that file only notices of their sessions, each of which is
    # that session's agenda however it is titled ("Informal Gathering 1 March
    # 2021", "1-March-2021-workshop-notice.pdf").
    notice_committees: frozenset[str] = frozenset()

    def __init__(self, council_name: str, state: str, base_url: str):
        super().__init__(council_name, state, base_url)
        # Host -> when the last request to it was sent (time.monotonic()).
        self._last_request_at: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _page_url(listing_url: str, start_rank: int = 1) -> str:
        """A listing page with only the size and pager parameters added.

        Neither `num_ranks` nor `start_rank` matches a Disallow line in the
        councils' robots.txt; `query=` and facet parameters do, and are
        never sent. See the module docstring.
        """
        url = f"{listing_url}?num_ranks={PAGE_SIZE}"
        if start_rank > 1:
            url += f"&start_rank={start_rank}"
        return url

    def _wait_for_crawl_delay(self, url: str) -> None:
        """Keep requests to one host `CRAWL_DELAY_SECONDS` apart.

        Through `fetcher.sleep`, so replay, where nothing is fetched, does
        not wait.
        """
        host = urllib.parse.urlparse(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            wait = CRAWL_DELAY_SECONDS - (time.monotonic() - last)
            if wait > 0:
                self.fetcher.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def _fetch_page(self, url: str) -> str:
        """One listing page through Chrome, retried once on a new browser.

        The retry is for a challenge that did not clear in time, which a
        fresh session usually does. It is a second request to the host, so
        it waits out the crawl delay too. During replay the cassette is keyed
        by URL, so a retry reads the same recording.
        """
        last_error: Optional[Exception] = None
        for attempt in range(2):
            self._wait_for_crawl_delay(url)
            try:
                return self.fetcher.fetch_with_selenium(
                    url,
                    wait_time=CHALLENGE_WAIT_SECONDS,
                    wait_condition=EC.presence_of_element_located(
                        (By.CSS_SELECTOR, _LISTING_SELECTOR)
                    ),
                )
            except Exception as error:
                last_error = error
                self.logger.warning(
                    f"{self.council_name}: listing page failed "
                    f"(attempt {attempt + 1}/2): {type(error).__name__}: {error}"
                )
                self.fetcher.restart_driver()
        raise last_error

    def _listing_documents(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        """Every document on a listing that may fall in a wanted year.

        Production asks for the current year only, which the first page of
        every listing here covers, so it stops there: once the sorted run has
        gone back past `earliest_year`, nothing later in the listing can be
        from a wanted year (see `NEWEST_UNSORTED_YEAR`). A run wanting older
        years reads the whole listing.
        """
        stop_early = earliest_year > NEWEST_UNSORTED_YEAR
        documents: list[_Listed] = []
        start_rank = 1
        for _ in range(MAX_PAGES):
            page, total = _parse_listing(
                self._fetch_page(self._page_url(listing_url, start_rank))
            )
            documents.extend(page)
            start_rank += len(page)
            if not page or total is None or start_rank > total:
                return documents
            dates = [d.date for d in page if d.date]
            if stop_early and dates and min(dates) < f"{earliest_year}-01-01":
                return documents
        self.logger.warning(
            f"{self.council_name}: stopped {listing_url} at {MAX_PAGES} pages; "
            f"the listing may hold more documents than were read"
        )
        return documents

    # ------------------------------------------------------------------
    # Assembling meetings
    # ------------------------------------------------------------------

    def _body_name(self, committee: str) -> str:
        """The body a committee label stands for, as a meeting type.

        Labels are often the name of the page the documents are listed on
        ("Audit Committee Agendas and Minutes"), so that suffix is dropped,
        and every label meaning the council itself becomes one name. That
        also makes this the grouping key: Port Adelaide Enfield's council
        meetings sit under "Full Council" until mid-2025 and "Agendas and
        minutes" after, and both are the same body.
        """
        name = self.committee_names.get(committee)
        if name is not None:
            return name
        stripped = _PAGE_SUFFIX.sub("", committee).strip()
        if committee.lower() in _COUNCIL_LABELS or stripped.lower() in _COUNCIL_LABELS:
            return COUNCIL_MEETING
        return stripped or committee

    def _meeting_name(self, meeting: _Meeting, documents: list[_Document]) -> str:
        """The body that met, qualified by the kind of sitting.

        The committee label is the same for an ordinary and a special
        meeting, so the kind comes from the chosen documents' titles—or was
        already decided when `_split_sittings` separated two sittings.
        """
        titles = " ".join(d.title for d in documents)
        sitting = meeting.sitting or _sitting(titles)
        if sitting.endswith("agm"):
            return "Annual General Meeting"
        if sitting.endswith("special") and not _SPECIAL.search(meeting.body):
            return f"Special {meeting.body}"
        return meeting.body

    def _document_url(self, asset_id: str) -> str:
        return f"{DOCUMENT_ROOT}/?a={asset_id}"

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        """The date to group a document under, or None to drop it.

        The meeting date as filed, except 1 January. That is Matrix's
        placeholder when nobody set the date, and no council meets on New
        Year's Day, so grouping on it invents a meeting that never happened.
        But several of these are real agendas and minutes whose title gives
        the true date—Port Adelaide Enfield's "30 March 2021 Minutes for
        Special Council Meeting", Gawler's "09 February 2023 - Council
        Assessment Panel Agenda". So the title date is used when it is in the
        same year (the year the document is grouped under), and the document
        is dropped otherwise: titles like "27-04-2010
        Council Agenda" on 2022-01-01 are stray old uploads.

        A title date that disagrees with any *other* filed date is not
        trusted to move the document. Derwent Valley's
        "22-July-2020-AGM-Agenda.pdf", filed under its 16 July council
        meeting, looks like a misfiled council AGM, but it is the Local
        Government Association of Tasmania's AGM agenda attached to that
        council meeting.
        """
        if not filed.endswith("-01-01"):
            return filed
        stated = _title_date(title)
        if stated and stated.year == year and (stated.month, stated.day) != (1, 1):
            return stated.isoformat()
        return None

    def _title_body(self, title: str, bodies: set[str]) -> str:
        """The body a document with no committee label belongs to.

        An empty label would otherwise mean the council itself (see
        `_COUNCIL_LABELS`), which is wrong for Gawler's "10-06-2021 - Council
        Assessment Panel Minutes", filed with no committee and no category.
        So the title is matched against the bodies the rest of the year's
        documents are filed under, longest name first.
        """
        lowered = title.lower()
        for body in sorted(bodies, key=len, reverse=True):
            if body != COUNCIL_MEETING and body.lower() in lowered:
                return body
        return COUNCIL_MEETING

    def _assemble(self, documents: list[_Listed], year: int) -> list[_Meeting]:
        """Group one year's listed documents into meetings."""
        meetings: dict[tuple[str, str], _Meeting] = {}
        bodies = {self._body_name(d.committee) for d in documents if d.committee}

        for listed in documents:
            if not listed.asset_id.isdigit() or listed.date is None:
                continue
            if listed.committee in self.skip_committees:
                continue
            # Only PDFs: the PDF fields must never hold a Word document
            # (Prospect's Access and Inclusion group) or a recording (a third
            # of Campbelltown's documents). A file name with no extension is
            # given the benefit of the doubt unless Matrix filed it as audio.
            file_type = (
                listed.filename.rsplit(".", 1)[-1].lower()
                if "." in listed.filename
                else ""
            )
            if file_type not in ("pdf", "") or listed.asset_type.startswith("audio"):
                continue

            date = self._meeting_date(listed.date, listed.title, year)
            if date is None:
                continue
            classified = _classify(
                listed.title,
                listed.filename,
                notices_are_agendas=listed.committee in self.notice_committees,
            )
            if not classified:
                continue
            kind, rank = classified
            # A title naming another date than the one it is filed under is
            # usually a document attached to this meeting, not its own
            # agenda: Derwent Valley's "22-July-2020-AGM-Agenda.pdf", filed
            # under its 16 July council meeting, is the Local Government
            # Association of Tasmania's AGM agenda. It still stands in when
            # nothing else was filed, as Campbelltown's 21 July 2025 agenda
            # misfiled under the 20th does (see `_rejoin_misdated`).
            stated = _title_date(listed.title)
            if stated is not None and stated.isoformat() != date:
                rank += 1

            if _COUNCIL_TITLE.search(listed.title):
                body = COUNCIL_MEETING
            elif listed.committee:
                body = self._body_name(listed.committee)
            else:
                body = self._title_body(listed.title, bodies)
            meeting = meetings.setdefault((body, date), _Meeting(body=body, date=date))
            document = _Document(
                asset_id=listed.asset_id,
                title=listed.title,
                rank=rank,
                file_type=file_type,
            )
            getattr(meeting, {"agenda": "agendas"}.get(kind, kind)).append(document)

        return list(meetings.values())

    def _records(self, meetings: list[_Meeting]) -> list[ScraperReturn]:
        chosen: list[_Chosen] = []
        for group in meetings:
            for meeting in (
                part
                for sitting in _split_sittings(group)
                for part in _pair_by_title_words(sitting)
            ):
                agenda, minutes = _fill(
                    _best(meeting.agendas), _best(meeting.minutes), meeting.unnamed
                )
                documents = [d for d in (agenda, minutes) if d]
                if not documents:
                    continue
                chosen.append(
                    _Chosen(
                        name=self._meeting_name(meeting, documents),
                        date=meeting.date,
                        agenda=agenda,
                        minutes=minutes,
                    )
                )

        records = []
        for meeting in _rejoin_misdated(chosen):
            agenda_url = (
                self._document_url(meeting.agenda.asset_id) if meeting.agenda else None
            )
            minutes_url = (
                self._document_url(meeting.minutes.asset_id)
                if meeting.minutes
                else None
            )
            records.append(
                ScraperReturn(
                    name=meeting.name,
                    date=meeting.date,
                    time=None,
                    webpage_url=(
                        self.listing_urls[0] if self.listing_urls else self.base_url
                    ),
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        records.sort(key=lambda r: (r.date, r.name or ""), reverse=True)
        return records

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        documents: dict[str, _Listed] = {}
        failed: list[str] = []
        for listing_url in self.listing_urls:
            try:
                listed = self._listing_documents(listing_url, min(wanted))
            except Exception as error:
                # Logged loudly and counted: one bad listing should not cost
                # the others, but a run where nothing could be read must fail
                # rather than report a council with no meetings.
                failed.append(listing_url)
                self.logger.warning(
                    f"{self.council_name}: could not read {listing_url}: "
                    f"{type(error).__name__}: {error}"
                )
                continue
            for document in listed:
                documents.setdefault(document.asset_id, document)

        if failed and len(failed) == len(self.listing_urls):
            raise RuntimeError(
                f"{self.council_name}: every listing page request failed "
                f"({failed}); the Cloudflare challenge may not have cleared"
            )

        by_year: dict[int, list[_Listed]] = {}
        for document in documents.values():
            if document.date:
                by_year.setdefault(int(document.date[:4]), []).append(document)
        meetings: list[_Meeting] = []
        for year in wanted:
            meetings.extend(self._assemble(by_year.get(year, []), year))

        records = self._records(meetings)
        if records:
            self.logger.info(
                f"{self.council_name} scraper found {len(records)} meetings"
            )
        else:
            self.logger.warning(
                f"{self.council_name}: {', '.join(self.listing_urls)} held no "
                f"agendas or minutes for {wanted}"
            )
        return records


# ----------------------------------------------------------------------
# Councils that moved to Resolve and left the rest here
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ArchiveListing:
    """One LGA SA listing page that a Resolve council still needs.

    A council that moved its meetings to Resolve leaves two things behind in
    its collection: the meetings from before the move, and any body it did not
    move (Charles Sturt's assessment panel). Each sits on a listing page of
    its own—the per-committee pages the council links, read exactly as
    `LGASAFunnelbackScraper` reads any listing.
    """

    #: The council's own listing page for this body, bare: no query string.
    url: str

    #: The first day this body's meetings are published on Resolve instead.
    #: Records dated on or after it are dropped, so a meeting is never
    #: returned from both sources, and a run wanting only later years does
    #: not read this listing at all. None for a body that never moved.
    until: Optional[datetime.date] = None

    #: Keep only records whose name matches: a listing filed under one body
    #: can carry a document whose title names another (see
    #: `_COUNCIL_TITLE`), and that body's meetings come from elsewhere.
    keep: Optional[re.Pattern] = None

    def wanted(self, years: set[int]) -> set[int]:
        if self.until is None:
            return set(years)
        return {year for year in years if year <= self.until.year}

    def sole_source(self, today: datetime.date) -> bool:
        """Whether this body has not moved to Resolve (yet), so this listing
        is the only place its current meetings are published."""
        return self.until is None or self.until > today

    def holds(self, record: ScraperReturn) -> bool:
        if self.until is not None and record.date >= self.until.isoformat():
            return False
        return not self.keep or bool(self.keep.search(record.name or ""))


class _ListingReader(LGASAFunnelbackScraper):
    """Reads `ArchiveListing`s on behalf of another scraper.

    It borrows that scraper's fetcher, so its Selenium requests are made,
    recorded and replayed as the owner's, and one reader serves every listing
    in a run so `CRAWL_DELAY_SECONDS` spaces them all.
    """

    def __init__(self, owner: BaseScraper):
        super().__init__(owner.council_name, owner.state, owner.base_url)
        self.fetcher = owner.fetcher
        self.logger = owner.logger

    def read(self, listing: ArchiveListing, years: set[int]) -> list[ScraperReturn]:
        self.listing_urls = (listing.url,)
        self.years_filter = sorted(years)
        return [record for record in self.scraper() if listing.holds(record)]


class ResolveWithLGASAArchive(ResolveScraper):
    """A Resolve council whose other meetings are on LGA SA listing pages.

    A subclass sets the Resolve attributes as usual and lists its
    `archive_listings`. Each listing is read only for the wanted years up to
    its `until`, so production, which asks for one year, opens Chrome only
    while the current year still reaches back before the move, or for a body
    that never moved.
    """

    # The listing pages are fetched through Chrome, which Cloudflare
    # challenges from GitHub's runners unless "HeadlessChrome" is stripped;
    # see the module docstring. The Resolve API calls go through requests,
    # which this flag does not touch.
    strip_headless_user_agent = True

    archive_listings: tuple[ArchiveListing, ...] = ()

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        reader = _ListingReader(self)
        results: list[ScraperReturn] = []
        read, failures = 0, []
        for listing in self.archive_listings:
            years = listing.wanted(wanted)
            if not years:
                continue
            read += 1
            try:
                results += reader.read(listing, years)
            except Exception as error:
                if listing.sole_source(clock.today()):
                    # Charles Sturt's assessment panel never moved: dropping
                    # this listing would drop the body for the night while
                    # the council reported success.
                    raise SoleSourceFailed(
                        f"{self.council_name}: could not read {listing.url}, "
                        f"the only source for that body: "
                        f"{type(error).__name__}: {error}"
                    ) from error
                # A lost listing for a body that moved is a warning, as in the
                # base scraper; every listing lost raises, and
                # `ResolveScraper.scraper` then keeps what Resolve returned or
                # fails the council if that is empty.
                failures.append(error)
                self.logger.warning(
                    f"{self.council_name}: could not read {listing.url}: "
                    f"{type(error).__name__}: {error}"
                )
        if failures and len(failures) == read:
            raise failures[-1]
        return results
