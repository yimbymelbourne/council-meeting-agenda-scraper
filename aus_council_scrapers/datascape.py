"""Council meeting papers on Datascape CMS sites.

Datascape is an ASP.NET CMS used by a handful of small WA and Victorian
councils (assets on `cdn-sites.datascape.cloud`, `mc-` CSS classes). Its
meetings module is the same on every site:

- A listing page with a GET filter form, `?category=<slug>&month=All&year=<Y>`.
  Without `month=All` it shows the current month only. One page holds the
  whole year, with no pager. Each entry is a `<li>` linking `?item=id:<id>`,
  with a heading, a `<time datetime>` and a category label.
- An item page per entry, linking its files under
  `/repository/libraries/id:<library>/hierarchy/...`. Many of those file
  names have no extension, and they still answer as PDFs.

So the papers cost one request per item, on top of one listing per year.
Every Datascape site's robots.txt sets `Crawl-delay: 7` for all agents, and
it is honoured here (`CRAWL_DELAY_SECONDS`), so a production year is one to
three minutes of wall time per council. `expected_seconds` on each subclass is
the measured cost, so main.py dispatches these councils first.

**The sites are one server, and it limits the client, not the site.**
Manjimup, Towong and Sandstone all resolve to Datascape's load balancer
`lb-dds-mc2.datascape.cloud`. One council read 7 s apart never had a problem
in over 100 requests. Two or three read in parallel, each 7 s apart, got
200s with empty bodies about two minutes in, for a minute or more: Towong's
recording lost 9 item pages in a row while Sandstone's ran beside it (20 Oct
2026). main.py runs councils in parallel, so the councils on that server take
turns (`backend`): one council at a time, and 7 s between any two requests
to it. Halls Creek sits behind Cloudflare, so the server never sees our
address, and it never had an empty page while running beside the others; it
is spaced on its own.

Taking turns makes the three a chain of about 270 s from dispatch (home IP,
20 Oct 2026), more than half of main.py's 480 s budget, and a waiting
council holds a worker. Two limits keep a slow night from eating the rest:
a council gives up after `MAX_TURN_WAIT_SECONDS` in the queue, and every
request reads with `REQUEST_TIMEOUT` rather than the fetcher's 60 s.

What an item is differs by council, and the councils are not tidy about it.
Manjimup, Towong and Sandstone file an item per meeting, but Sandstone filed
one item per *year* for 2020-2022 and bundles an ordinary, a special and an
electors' meeting into one item when they fall in one month. Halls Creek files
an item per *document* (`items_are_documents`). So the base class reads
documents, not items, and builds meetings out of them:

- **What a document is** comes from its own label: the first of "agenda" or
  "minutes" it names ("Minutes Agenda 30 September 2021" at Manjimup is the
  minutes). Attachments, supplementary and late items, addenda and
  recordings are not the paper and are dropped. An agenda bundled with its
  attachments is used only when the plain agenda is not there; confirmed
  minutes beat unconfirmed ones. A paper whose label names neither is the
  one its meeting is missing, where that is unambiguous
  (`_settle_unlabelled`).
- **Which meeting body** comes from the document's label, then the item's
  title, then its category. Only ordinary and special Council meetings are
  kept: electors' meetings, committees and trusts are left out, which also
  keeps the request count down.
- **The date** comes from the document's own label or file name when it
  names a full date, then from the item's title. The listing's `Date:` field
  is used only where the title gives that same month and year and no day
  (Sandstone's "July Ordinary Council Meeting 2026"): Towong has placeholder
  dates there (1 April, 1 March), and Halls Creek's are upload dates. A
  document's own date beats its item's because councils file papers under
  the wrong item: Manjimup's 19 August 2021 item links the 17 December 2020
  agenda (`OC_17122020_AGN.pdf`), and Towong's "23 July 2021" item holds the
  23 June papers. The exception is a label that differs from its item only in
  the year, which is a typo ("Agenda 3 March 2023" on the 3 March 2022 item).
  A listed date also gives way to a different day the item's own files name
  for the meeting, because the field is not always moved with a meeting
  (`_correct_listed_dates`).
- **A document that names only a month** joins the one meeting of the same
  body that month whose date is known from another document (Halls Creek's
  "Ordinary Council Meeting Agenda September 2026" and its "Minutes 24
  September 2026"), or failing that from a recording or attachment named for
  the meeting (`_group`). Failing both, a subclass can date it from the
  covers of closed years' papers (`known_meeting_dates`) or, at Halls Creek,
  from an agenda's listing on the meeting weekday (`listed_meeting_weekday`).
  Otherwise it is left out with a warning rather than given a day nobody
  wrote down.
- **An item per document** (Halls Creek) is read file name first, title
  second, link text last; see `_document_item_facts` for why.

Upcoming meetings are listed with no papers until the agenda is out, and are
left out. Items more than `UPCOMING_WINDOW_DAYS` ahead are not fetched at
all, since nothing will be on them yet.
"""

from __future__ import annotations

import datetime
import re
import threading
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import isoparse

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.walkerdesigns import find_date as _find_written_date

# `Crawl-delay: 7` for `User-agent: *` in every Datascape council's robots.txt
# (checked for Manjimup, Towong, Halls Creek and Sandstone, 20 Oct 2026). The
# fetcher's own per-host spacing is FETCH_DELAY, 2 s, which is shorter, so the
# scraper waits out the rest itself.
CRAWL_DELAY_SECONDS = 7.0

# (connect, read) seconds for every request here, in place of the fetcher's
# (10, 60). The read timeout is the longest gap allowed between bytes. These
# pages answer in a second or two, and the one stall seen (Towong, 20 Oct
# 2026) sent nothing at all, so 30 s loses nothing real. It halves the cost
# of a stalled page, which `_page` asks for twice: at 60 s that was about
# 134 s, a big share of the shared server's run (see `MAX_TURN_WAIT_SECONDS`).
# Passed per request, so `FETCH_TIMEOUT` does not reach these councils.
REQUEST_TIMEOUT = (10.0, 30.0)

# How long a council waits for its turn on a shared server before it gives
# up. The three councils on lb-dds-mc2 take 70-100 s each for a production
# year, so the last in line normally waits about 160-185 s and finishes about
# 270 s after dispatch (measured 20 Oct 2026, home IP). A council still
# waiting at 300 s would end at 370-400 s at best, close to main.py's 480 s
# budget. Waiting longer also holds a worker that other councils could use.
# So it fails then, as a TimeoutError, and its stored meetings stay as they
# were.
MAX_TURN_WAIT_SECONDS = 300.0

# Where `backend` names the same server, the councils on it take turns: one
# lock per server, held for a whole run, and the time of the last request to
# it. Process-wide, because main.py runs every council in one process.
_BACKEND_GUARD = threading.Lock()
_BACKEND_LOCKS: dict[str, threading.Lock] = {}
_BACKEND_LAST_REQUEST: dict[str, float] = {}


def _backend_lock(backend: str) -> threading.Lock:
    with _BACKEND_GUARD:
        return _BACKEND_LOCKS.setdefault(backend, threading.Lock())


# Agendas go up about a week before the meeting. An item further ahead than
# this has nothing on it yet, so fetching it would cost 7 s for nothing.
UPCOMING_WINDOW_DAYS = 21

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
_MONTH_WORD = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.IGNORECASE
)
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
# InfoCouncil-style file names, `OC_17122020_AGN.pdf`, which Manjimup still
# uploads now and then.
_COMPACT_DATE = re.compile(r"(?<!\d)(\d\d)(\d\d)(20\d\d)(?!\d)")

# `_MIN` and `_AGN` are InfoCouncil's file-name codes ("OC_17082023_MIN_SAVED").
_MINUTES = re.compile(r"minute|_MIN(?![a-z])", re.IGNORECASE)
_AGENDA = re.compile(r"agenda|_AGN(?![a-z])", re.IGNORECASE)
# "Council Meeting Combined Agenda and Attachments": the agenda, but a far
# bigger file, so the plain agenda is preferred when both are there.
_WITH_ATTACHMENTS = re.compile(
    r"(?:agenda|minutes)\s*(?:and|with|&|\+)\s*attach", re.IGNORECASE
)
# Not the paper: attachments on their own (Manjimup spells it "Attachements"
# once), supplementary and late items, addenda, recordings and presentations.
_NOT_THE_PAPER = re.compile(
    r"\battache?ments?\b|supplementary|\blate\b|addendum|\baudio\b|recording"
    r"|\bvideo\b|presentation|\bagenda\s+items?\b",
    re.IGNORECASE,
)
# Sandstone's "Updated AGENDA Special Meeting 06 August 2026".
_SUPERSEDES = re.compile(r"\bamended\b|\bupdated?\b|\brevised\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed|\bdraft\b", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed|\bsigned\b", re.IGNORECASE)

# Meeting bodies, most specific first: "Special Meeting Agenda" is special,
# "Audit Committee Minutes" is a committee whatever else it says.
_BODIES = (
    ("electors", re.compile(r"elector", re.IGNORECASE)),
    (
        "committee",
        re.compile(
            r"\baudit\b|committee|\bARIC\b|\btrust\b|briefing|forum|workshop",
            re.IGNORECASE,
        ),
    ),
    # Manjimup calls two of its special meetings "Extraordinary".
    ("special", re.compile(r"\bspecial\b|extraordinary|\bSCM\b", re.IGNORECASE)),
    ("ordinary", re.compile(r"\bordinary\b|\bOCM\b", re.IGNORECASE)),
)
# The bodies kept. Electors' meetings, committees and trusts are not Council
# meetings.
_MEETING_NAMES = {
    "ordinary": "Ordinary Council Meeting",
    "special": "Special Council Meeting",
}
_SIZE = re.compile(r"\s*\((?:PDF, )?[\d.]+\s*[KMG]?B\)\s*$", re.IGNORECASE)


def _clean(text: str) -> str:
    return " ".join(text.split())


# A list number before a month, "Collated attachments 1. December 2020", is
# not a day.
_LIST_NUMBER = re.compile(r"(?<!\d)\d{1,2}\.\s+(?=[a-z])", re.IGNORECASE)


def find_date(text: str) -> Optional[datetime.date]:
    """The first full date written in `text`, including `ddmmyyyy` file names."""
    if not text:
        return None
    text = _LIST_NUMBER.sub(" ", text)
    date = _find_written_date(text)
    if date is not None:
        return date
    m = _COMPACT_DATE.search(text)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


_NAMED_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\.?,?\s+(20\d\d)(?!\d)",
    re.IGNORECASE,
)


def find_named_date(text: str) -> Optional[datetime.date]:
    """The first "24 September 2026"-style date in `text`: day, month in words, year."""
    if not text:
        return None
    for m in _NAMED_DATE.finditer(_LIST_NUMBER.sub(" ", text.replace("_", " "))):
        try:
            return datetime.date(
                int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))
            )
        except ValueError:
            continue
    return None


# "SIGNED Minutes of the Ordinary Council Meeting for August 2025 actual
# meeting held 1st September.pdf" (Sandstone): the day the meeting was held,
# often with no year.
_HELD = re.compile(
    r"\bheld\s+(?:on\s+)?(?:[a-z]+day,?\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\b\.?,?(?:\s+(20\d\d)(?!\d))?",
    re.IGNORECASE,
)


def find_held_date(
    text: str, near: Optional[datetime.date]
) -> Optional[datetime.date]:
    """The day in "held 1st September", in the year that puts it nearest `near`.

    Without a year written and without `near` there is no telling, so None.
    """
    if not text:
        return None
    m = _HELD.search(text.replace("_", " "))
    if not m:
        return None
    day, month = int(m.group(1)), _MONTHS[m.group(2).lower()]
    years = [int(m.group(3))] if m.group(3) else []
    if not years:
        if near is None:
            return None
        years = [near.year - 1, near.year, near.year + 1]
    candidates = []
    for year in years:
        try:
            candidates.append(datetime.date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    if near is None:
        return candidates[0]
    return min(candidates, key=lambda d: abs((d - near).days))


def find_month(text: str) -> Optional[tuple[int, int]]:
    """(year, month) where `text` names a month and a year anywhere in it.

    Sandstone writes "July Ordinary Council Meeting 2026", so the two need
    not be next to each other.
    """
    if not text:
        return None
    month = _MONTH_WORD.search(text.replace("_", " "))
    year = _YEAR.search(text)
    if not month or not year:
        return None
    return int(year.group(1)), _MONTHS[month.group(1).lower()]


def _body(text: str) -> Optional[str]:
    for body, pattern in _BODIES:
        if pattern.search(text):
            return body
    return None


def _bodies(text: str) -> set[str]:
    return {body for body, pattern in _BODIES if pattern.search(text)}


def _kind(text: str) -> Optional[str]:
    """ "agenda" or "minutes", whichever the text names first.

    A meeting's paper that is confirmed or signed is its minutes, so
    "Council Meeting - 23 July 2025 - Confirmed.pdf" (Towong) is the
    minutes. Only a meeting's: Sandstone also uploads "Annual Report
    2023-2024 confirmed" and "Signed financial statements".
    """
    agenda = _AGENDA.search(text)
    minutes = _MINUTES.search(text)
    if agenda and (not minutes or agenda.start() < minutes.start()):
        return "agenda"
    if minutes:
        return "minutes"
    if re.search(r"\bmeeting\b", text, re.IGNORECASE) and (
        _CONFIRMED.search(text) or _UNCONFIRMED.search(text)
    ):
        return "minutes"
    return None


@dataclass
class DatascapeItem:
    """One entry on a year's listing."""

    url: str
    title: str
    category: str
    # The listing's `Date:` field, in the council's own time zone. What it
    # means varies by council; see the module docstring.
    when: Optional[datetime.datetime]

    @property
    def title_date(self) -> Optional[datetime.date]:
        return find_date(self.title)

    @property
    def listed_date(self) -> Optional[datetime.date]:
        return self.title_date or (self.when.date() if self.when else None)


@dataclass
class DatascapeDocument:
    url: str
    label: str
    # "agenda" or "minutes"; None until `_settle_unlabelled` decides, and
    # for anything that is not the paper.
    kind: Optional[str]
    body: str
    date: Optional[datetime.date]
    month: Optional[tuple[int, int]]
    item: DatascapeItem
    # Where it sits on its item page, to break ties in the order the council
    # chose.
    position: int
    # False for attachments, recordings and other files that are never
    # stored, but may still say when the meeting was (see `_group`).
    paper: bool = True
    # Whether `date` was written on the document itself rather than taken
    # from its item.
    own_date: bool = False
    names_meeting: bool = False
    # Whether `date` is the listing's `Date:` field, which the item's own
    # files can overrule (see `_correct_listed_dates`).
    from_listing: bool = False

    def rank(self) -> tuple:
        if self.kind == "agenda":
            return (
                bool(_WITH_ATTACHMENTS.search(self.label)),
                not _SUPERSEDES.search(self.label),
                self.position,
            )
        if _UNCONFIRMED.search(self.label):
            confirmed = 2
        elif _CONFIRMED.search(self.label):
            confirmed = 0
        else:
            confirmed = 1
        return (confirmed, bool(_WITH_ATTACHMENTS.search(self.label)), self.position)


class DatascapeMeetingsScraper(BaseScraper):
    """Reads a Datascape meetings listing, a page per year and per item.

    A subclass supplies `listing_url` (the meetings page, without a query)
    and, where the listing carries more than Council meetings, `category`
    (the filter's slug) or `keep_categories` (a pattern on each entry's
    category label). `items_are_documents` is for a council that files one
    item per document rather than per meeting.
    """

    listing_url: str
    # The filter's `category` value; empty for every meeting type.
    category: str = ""
    # A pattern the entry's category label must match, for councils whose
    # filter cannot pick out Council meetings in one value.
    keep_categories: Optional[str] = None
    # Halls Creek: an item per document, its title naming what it is.
    items_are_documents: bool = False
    # Whether the listing's `Date:` field is the meeting's date where the
    # title gives only the month (see the module docstring).
    trust_listed_dates: bool = True
    # Halls Creek: the weekday (Monday 0) on which a month-only agenda's
    # listing `Date:` is the meeting's day rather than an upload stamp. Used
    # only where nothing else dates the agenda (see `_month_only_date`).
    listed_meeting_weekday: Optional[int] = None
    # Days read from the papers' own covers, for meetings whose papers name
    # only the month and that nothing on the site dates: {(body, year,
    # month): day}. For closed years only, where the papers will not change.
    known_meeting_dates: dict[tuple[str, int, int], datetime.date] = {}
    # The first year the council's listing holds, where that is later than
    # EARLIEST_YEAR, so a full run does not ask for years it never had.
    earliest_year: int = EARLIEST_YEAR
    # The server the site is served from, where councils share one (see the
    # module docstring). None for a site with a server of its own as far as
    # we can tell, which is then spaced by its own host name.
    backend: Optional[str] = "lb-dds-mc2.datascape.cloud"

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        years = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        return {y for y in years if y >= self.earliest_year}

    def _backend_key(self) -> str:
        return self.backend or urllib.parse.urlparse(self.listing_url).netloc

    def _get(self, url: str) -> str:
        """Fetch with `CRAWL_DELAY_SECONDS` between requests to the server.

        The wait goes through `fetcher.sleep`, so replay does not wait.
        Measured from the end of the previous response, so a slow page does
        not eat into the gap, and from the last request any council made to
        the same server, so the next council in line waits too.
        """
        key = self._backend_key()
        last = _BACKEND_LAST_REQUEST.get(key)
        if last is not None:
            wait = CRAWL_DELAY_SECONDS - (time.monotonic() - last)
            if wait > 0:
                self.fetcher.sleep(wait)
        try:
            return self.fetcher.fetch_with_requests(url, timeout=REQUEST_TIMEOUT)
        finally:
            _BACKEND_LAST_REQUEST[key] = time.monotonic()

    def _page(self, url: str, marker: str):
        """The element with id `marker` on `url`, asking twice if need be.

        Datascape's server answers 200 with an empty body when it thinks a
        client is going too fast (see the module docstring), and the same URL
        answered in full when asked again later. Taking turns should keep us
        under that, but the limit is not published, so a page without its
        marker is asked for once more, a crawl delay later, before it counts
        as a failure. So is a page that fails to arrive: Towong once held an
        item page past the 60 s read timeout with nothing else asking it for
        anything (20 Oct 2026), then the 60 s read timeout, now
        `REQUEST_TIMEOUT`. Every
        listing has `#meeting-listing` and every item page `#meeting` (all
        419 item pages read while building this), so a page still without it
        is a challenge, an error page or a redesign. Raising then matters
        most for item pages: read as a page with no papers, it would drop
        its meeting without a word.
        """
        for attempt in range(2):
            try:
                html = self._get(url)
            except Exception as error:
                if attempt == 1:
                    raise
                self.logger.warning(
                    f"{self.council_name}: {url} failed "
                    f"({type(error).__name__}: {error}); asking again"
                )
                continue
            soup = BeautifulSoup(html, "html.parser")
            found = soup.find(id=marker)
            if found is not None:
                return found
            # Say what came back instead, so a night's log tells a challenge
            # page from an error page from a redesign.
            title = _clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
            text = _clean(soup.get_text(" ", strip=True))[:200]
            message = (
                f"{self.council_name}: no #{marker} on {url} "
                f"(title {title!r}; text {text!r})"
            )
            if attempt == 1:
                raise ValueError(message)
            self.logger.warning(message + "; asking again")
        raise AssertionError("unreachable")

    def _listing_url(self, year: int) -> str:
        query = urllib.parse.urlencode(
            {"category": self.category, "month": "All", "year": year}
        )
        return f"{self.listing_url}?{query}"

    def _listing(self, year: int) -> tuple[list[DatascapeItem], set[int]]:
        """A year's entries, and the years the filter offers.

        Raises when the page has no meeting listing: that is a changed
        template or a challenge page, and reading it as an empty year would
        report the council as fine with no meetings.
        """
        url = self._listing_url(year)
        listing = self._page(url, "meeting-listing")
        year_select = listing.find("select", attrs={"name": "year"})
        offered = {
            int(option["value"])
            for option in (year_select.find_all("option") if year_select else [])
            if option.get("value", "").isdigit()
        }
        items = []
        for li in listing.find_all("li"):
            link = li.find("a", href=True)
            if link is None or "item=id:" not in link["href"]:
                continue
            heading = li.find(["h2", "h3"])
            stamp = li.find("time", attrs={"datetime": True})
            category = li.select_one(".category")
            when = None
            if stamp is not None:
                try:
                    when = isoparse(stamp["datetime"])
                except ValueError:
                    when = None
            items.append(
                DatascapeItem(
                    url=urllib.parse.urljoin(url, link["href"]),
                    title=_clean(heading.get_text(" ", strip=True) if heading else ""),
                    category=(
                        _clean(category.get_text(" ", strip=True)) if category else ""
                    ),
                    when=when,
                )
            )
        return items, offered

    # ------------------------------------------------------------------
    # Reading an item
    # ------------------------------------------------------------------

    def _item_body(self, item: DatascapeItem) -> str:
        """The body a document belongs to when it does not say.

        Ordinary first: Sandstone's "2025 February Ordinary, Special and
        Electors Meetings" item names its special and electors' papers as
        such, and its unlabelled ones are the ordinary meeting's.
        """
        title = item.title
        if "ordinary" in _bodies(title):
            return "ordinary"
        return _body(title) or _body(item.category) or "ordinary"

    def _item_date(self, item: DatascapeItem) -> Optional[datetime.date]:
        if item.title_date is not None:
            return item.title_date
        if len(_bodies(item.title) & set(_MEETING_NAMES)) > 1:
            # "2025 February Ordinary, Special and Electors Meetings" is
            # listed on 6 February, the special meeting's day; the ordinary
            # meeting was on the 27th. Which meeting the field means is not
            # knowable, so it is not used. A committee or electors' meeting
            # beside one Council meeting does not count: Sandstone's "2023
            # June (Ordinary, Electors and Audit)", "2023 March (Ordinary and
            # Audit)", "February 2024 (Ordinary and Audit)" and "March 2024
            # Ordinary and Electors" are listed on the ordinary meeting's day
            # (checked against the agendas).
            return None
        if self.trust_listed_dates and item.when is not None:
            month = find_month(item.title)
            if month == (item.when.year, item.when.month):
                return item.when.date()
        return None

    def _document(
        self, item: DatascapeItem, url: str, label: str, position: int
    ) -> Optional[DatascapeDocument]:
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        directory, _, filename = path.rpartition("/")
        stem, dot, extension = filename.rpartition(".")
        # Recordings (.mp3) and the odd Word file are not the paper.
        # Extensionless names are PDFs. ("11.12.2025 Ordinary Council
        # Meeting Recording.mp3" and "... February 2025 6.02.2025" have dots
        # in their names, so only a short tail with a letter in it counts as
        # an extension.)
        if not (
            dot and re.fullmatch(r"(?=[a-z0-9]*[a-z])[a-z0-9]{2,4}", extension, re.I)
        ):
            stem, extension = filename, ""
        # For an item per document, the item's title is the document's name.
        name = f"{item.title} {label}" if self.items_are_documents else label
        # "Combined Agenda and Attachments" is the agenda, so the word
        # "Attachments" there does not rule it out.
        paper = extension.lower() in ("", "pdf") and not (
            _NOT_THE_PAPER.search(_WITH_ATTACHMENTS.sub(" ", name))
            or _NOT_THE_PAPER.search(_WITH_ATTACHMENTS.sub(" ", stem))
        )
        body = _body(name) or _body(stem) or self._item_body(item)
        if body not in _MEETING_NAMES:
            return None
        if self.items_are_documents:
            kind, date, month = self._document_item_facts(item, label, stem)
            kind = kind if paper else None
        else:
            # None for a paper that does not say; `_documents` decides those.
            kind = (_kind(name) or _kind(stem)) if paper else None
            # "held 1st September" first: where a label names both, the
            # month it was due and the day it was held, the day held is the
            # meeting's.
            date = (
                find_held_date(f"{label} {stem}", item.when.date() if item.when else None)
                or find_date(label)
                or find_date(stem)
            )
            month = (
                find_month(name)
                or find_month(stem)
                or find_month(directory.rsplit("/", 1)[-1] + " " + directory)
            )
        own_date = date is not None
        from_listing = False
        if not self.items_are_documents:
            item_date = self._item_date(item)
            if (
                date is None
                and item_date is not None
                and body == self._item_body(item)
                and month in (None, (item_date.year, item_date.month))
            ):
                date = item_date
                from_listing = item.title_date is None
            elif (
                date is not None
                and item_date is not None
                and date != item_date
                and (date.month, date.day) == (item_date.month, item_date.day)
            ):
                # The same day and month in another year is a typo in the
                # label, not a paper filed under the wrong meeting:
                # Manjimup's 3 March 2022 item links "Agenda 3 March 2023",
                # and its 21 January 2021 item has all three papers labelled
                # 2024.
                date = item_date
        # Whether the file itself names a Council meeting, which a file that
        # is not the paper must do to date one (see `_group`): Sandstone's
        # audit papers ("Opinion - Shire of Sandstone - 30 June 2022") do not.
        names_meeting = bool(
            (_bodies(name) | _bodies(stem)) & set(_MEETING_NAMES)
            or re.search(r"council\s+meeting", f"{name} {stem}", re.IGNORECASE)
        )
        if not paper:
            return DatascapeDocument(
                url=url,
                label=label,
                kind=None,
                body=body,
                date=date if own_date else None,
                month=None,
                item=item,
                position=position,
                paper=False,
                own_date=own_date,
                names_meeting=names_meeting,
            )
        if date is not None:
            month = (date.year, date.month)
        return DatascapeDocument(
            url=url,
            label=label,
            kind=kind,
            body=body,
            date=date,
            month=month,
            item=item,
            position=position,
            own_date=own_date,
            names_meeting=names_meeting,
            from_listing=from_listing,
        )

    @staticmethod
    def _document_item_facts(
        item: DatascapeItem, label: str, stem: str
    ) -> tuple[Optional[str], Optional[datetime.date], Optional[tuple[int, int]]]:
        """Kind, date and month of an item that is one document (Halls Creek).

        The file name is read first, then the listing title, then the link
        text, because the titles are the least reliable of the three: the
        item "Ordinary Council Meeting Agenda July 2020" links "Unconfirmed
        Minutes - July Council Meeting - 23 July 2020 (002).pdf", "Special
        Council Meeting Agenda April 2025" the minutes of 14 April, "Ordinary
        Council Meeting Agenda August 2023" the October agenda, and one
        "Ordinary Council Meeting Minutes May 2022" item links every 2022
        paper (all checked against the PDFs). The link text comes last
        because it is retyped by hand: the 30 September 2026 special
        minutes are linked as "... 17 September 2026".

        Numbers are never read as a date here, only a day with the month in
        words: since 2026 the file names lead with when the file was saved,
        not when the meeting was ("2026.07.29 - Special Meeting 30 July
        Agenda", "OCM 21 May 2026 [Agenda] 20.05.2026 @ 1247hrs").
        """
        kind = _kind(stem) or _kind(item.title) or _kind(label) or _kind(item.category)
        date = (
            find_named_date(stem)
            or find_named_date(item.title)
            or find_named_date(label)
        )
        month = find_month(stem) or find_month(item.title) or find_month(label)
        return kind, date, month

    def _documents(self, item: DatascapeItem) -> list[DatascapeDocument]:
        container = self._page(item.url, "meeting")
        documents = []
        for position, link in enumerate(container.find_all("a", href=True)):
            href = link["href"].strip()
            if "/repository/" not in href:
                continue
            name = link.select_one(".name")
            label = _clean(
                (name or link).get_text(" ", strip=True).replace("\u200b", "")
            )
            label = _SIZE.sub("", label)
            document = self._document(
                item, urllib.parse.urljoin(item.url, href), label, position
            )
            if document is not None:
                documents.append(document)
        self._correct_listed_dates(documents)
        return self._settle_unlabelled(documents)

    # Furthest a meeting is moved from its listed day on the word of the
    # item's own files. A meeting put back a few days stays in this; the
    # previous month's minutes filed on the item would not.
    MOVED_MEETING_DAYS = 14

    def _correct_listed_dates(self, documents: list[DatascapeDocument]) -> None:
        """Re-date papers dated by the listing where the item's files disagree.

        The listing's `Date:` is set when the item is made and is not always
        moved with the meeting. Sandstone's "2025 August" item is listed for
        Thursday 28 August, but the meeting was moved to Monday 1 September:
        the item holds a notice of the change, a "01-09-2025 Ordinary Council
        Meeting Recording" and minutes "... actual meeting held 1st
        September", and the agenda's cover says 1 September (checked 20 Oct
        2026). So where a file on the item names its own day for a meeting
        of the same body, and none names the listed day, that day wins if it
        is the only one within `MOVED_MEETING_DAYS`. Where two days compete,
        or the only one is further off, the papers dated by the listing lose
        their date and are left to `_group`, which drops them with a warning
        rather than guess.
        """
        listed = [d for d in documents if d.from_listing and d.date is not None]
        for body in {d.body for d in listed}:
            mine = [d for d in listed if d.body == body]
            listed_day = mine[0].date
            named = {
                d.date
                for d in documents
                if d.own_date
                and d.date is not None
                and d.body == body
                and (d.paper or d.names_meeting)
            }
            if not named or listed_day in named:
                continue
            near = {
                day
                for day in named
                if abs((day - listed_day).days) <= self.MOVED_MEETING_DAYS
            }
            item = mine[0].item
            if len(near) == 1:
                (day,) = near
                self.logger.info(
                    f"{self.council_name}: {item.url} is listed on {listed_day} "
                    f"but its files name {day}; using {day}"
                )
            else:
                day = None
                self.logger.warning(
                    f"{self.council_name}: {item.url} is listed on {listed_day} "
                    f"but its files name {sorted(str(x) for x in named)}; its "
                    f"papers dated only by the listing are left undated"
                )
            for document in mine:
                document.date = day
                document.from_listing = False
                if day is not None:
                    document.month = (day.year, day.month)

    def _settle_unlabelled(
        self, documents: list[DatascapeDocument]
    ) -> list[DatascapeDocument]:
        """Decide what a paper that names neither agenda nor minutes is.

        It is the one the meeting is missing, where that is unambiguous: one
        such paper on the item, every other paper on it belonging to one
        meeting, and that meeting short of exactly one of the two. Manjimup's
        16 December 2025 item links "Council Meeting Agenda 16 December 2025"
        and a bare "Council Meeting 16 December 2025", which is the
        unconfirmed minutes; Towong's 14 May 2025 special meeting has its
        minutes labelled and its agenda as "Special_Council_Meeting_14 May
        2025.pdf" (both checked against the PDFs). Anything less clear-cut is
        left out.
        """
        unlabelled = [d for d in documents if d.kind is None and d.paper]
        labelled = [d for d in documents if d.kind is not None]
        others = [d for d in documents if not d.paper]
        if not unlabelled or self.items_are_documents:
            return labelled + others
        meetings = {(d.body, d.date) for d in labelled}
        if len(unlabelled) == 1 and len(meetings) == 1:
            document = unlabelled[0]
            missing = {"agenda", "minutes"} - {d.kind for d in labelled}
            if (
                len(missing) == 1
                and document.date is not None
                and (document.body, document.date) in meetings
            ):
                document.kind = missing.pop()
                return labelled + [document] + others
        for document in unlabelled:
            self.logger.info(
                f"{self.council_name}: {document.label!r} on {document.item.url} "
                f"names neither agenda nor minutes; left out"
            )
            document.paper = False
            if not document.own_date:
                document.date = None
        return labelled + unlabelled + others

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    def _group(
        self, documents: list[DatascapeDocument]
    ) -> dict[tuple[str, datetime.date], list[DatascapeDocument]]:
        """Papers by (body, date), with month-only papers placed where they can be.

        A month-only paper joins the one meeting of its body that month that
        a dated paper establishes. Where no paper dates it, a file that is
        not a paper but names its own date may: Sandstone's February 2025
        item has "Agenda February 2025.pdf" and "Minutes February 2025.pdf"
        beside an "Ordinary Council Meeting February 2025 27.02.2025"
        file, and its 2020 bundle a "Compiled Attachments Ordinary Council
        Meeting 24 September 2020.pdf". Those only count where no paper
        dates a meeting of that body that month.
        """
        meetings: dict[tuple[str, datetime.date], list[DatascapeDocument]] = (
            defaultdict(list)
        )
        witnessed: dict[tuple[str, tuple[int, int]], set[datetime.date]] = defaultdict(
            set
        )
        undated = []
        for document in documents:
            if not document.paper:
                if (
                    document.date is not None
                    and document.own_date
                    and document.names_meeting
                ):
                    witnessed[
                        (document.body, (document.date.year, document.date.month))
                    ].add(document.date)
            elif document.date is not None:
                meetings[(document.body, document.date)].append(document)
            else:
                undated.append(document)
        # A month-only paper that nothing on the site places may still be
        # dated from what is known about the council (`_month_only_date`).
        # Done first, and only for a month no paper or file dates, so that the
        # month-only papers left over can join the meeting it makes.
        # Which months the papers date, taken before any of this adds to
        # `meetings`: Sandstone's June 2022 meeting was held on 8 July, and
        # must not stop the July papers being dated in their own right.
        dated_months = {(body, (day.year, day.month)) for body, day in meetings}
        leftover = []
        for document in undated:
            day = None
            if (
                document.month is not None
                and (document.body, document.month) not in dated_months
                and not witnessed.get((document.body, document.month))
            ):
                day = self._month_only_date(document)
            if day is None:
                leftover.append(document)
            else:
                meetings[(document.body, day)].append(document)
        for document in leftover:
            matches = [
                key
                for key in meetings
                if key[0] == document.body
                and (key[1].year, key[1].month) == document.month
            ]
            if not matches:
                matches = [
                    (document.body, date)
                    for date in witnessed.get((document.body, document.month), ())
                ]
            if len(matches) == 1:
                meetings[matches[0]].append(document)
                continue
            if document.month is None:
                why = "it names no date"
            elif matches:
                why = f"{len(matches)} {document.body} meetings that month"
            else:
                why = "no other paper names the day"
            self.logger.warning(
                f"{self.council_name}: left out {document.label!r} "
                f"({document.item.url}): {why}"
            )
        return meetings

    def _month_only_date(
        self, document: DatascapeDocument
    ) -> Optional[datetime.date]:
        """The day of a month-only paper that no paper or file on the site gives.

        From `known_meeting_dates` first: days read once from the papers'
        own covers. Then, where the council sets `listed_meeting_weekday`,
        from an agenda's listing `Date:`, if it falls on that weekday in the
        named month at midnight. At Halls Creek that is the meeting's day
        every time, and it is the only date an upcoming agenda named by
        month has. All 49 agenda entries on its listing that fall on a
        Thursday at midnight in their own month were listed on the meeting's
        day, checked against the minutes, the file name or the agenda's
        cover (20 Oct 2026). Upload stamps fall on other days or carry a
        time (Tuesday 29 July 2025 11:49; Wednesday 16 September 2026, the
        agenda briefing for the 24th). Minutes are left out of this: theirs
        are later uploads, and a month-only paper of the same meeting joins
        the agenda's day in `_group`.
        """
        year, month = document.month
        known = self.known_meeting_dates.get((document.body, year, month))
        if known is not None:
            return known
        when = document.item.when
        if (
            self.listed_meeting_weekday is not None
            and document.kind == "agenda"
            and document.body == "ordinary"
            and when is not None
            and (when.year, when.month) == (year, month)
            and when.weekday() == self.listed_meeting_weekday
            and (when.hour, when.minute) == (0, 0)
        ):
            return when.date()
        return None

    def _meeting(
        self, body: str, date: datetime.date, documents: list[DatascapeDocument]
    ) -> Optional[ScraperReturn]:
        def best(kind: str) -> Optional[DatascapeDocument]:
            candidates = [d for d in documents if d.kind == kind]
            return min(candidates, key=DatascapeDocument.rank) if candidates else None

        agenda, minutes = best("agenda"), best("minutes")
        if agenda is None and minutes is None:
            return None
        meeting_time = None
        if not self.items_are_documents:
            for document in documents:
                when = document.item.when
                if (
                    when is not None
                    and when.date() == date
                    # Midnight and 1 am (Halls Creek, Sandstone) and 00:01
                    # (Towong) are placeholders, and Towong's 14 May 2025
                    # special meeting is listed at 2:36 pm but its agenda
                    # says 10 am. Meetings start on the quarter hour, in the
                    # working day or the evening.
                    and 7 <= when.hour <= 21
                    and when.minute % 15 == 0
                    and self._item_body(document.item) == body
                ):
                    meeting_time = when.strftime("%I:%M %p").lstrip("0")
                    break
        agenda_url = agenda.url if agenda else None
        minutes_url = minutes.url if minutes else None
        return ScraperReturn(
            name=_MEETING_NAMES[body],
            date=date.isoformat(),
            time=meeting_time,
            webpage_url=(agenda or minutes).item.url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _keeps(self, item: DatascapeItem) -> bool:
        if self.keep_categories is None:
            return True
        return bool(re.search(self.keep_categories, item.category, re.IGNORECASE))

    def _check_years_have_meetings(self, wanted, with_papers: set[int]) -> None:
        """Fail the current year when it is under way and has no papers.

        Each of these councils meets monthly, so a year three months in with
        nothing means the listing or the item pages changed shape, not that
        the council stopped meeting. Raising makes production, which asks for
        the current year only, report the council as failed rather than as
        fine with 0 meetings. The first 90 days only warn: January is often a
        recess. A past year only warns, because it can be empty for a reason
        that is the council's: Sandstone's 2022 papers are named by month
        only, and before `known_meeting_dates` none of them could be dated.
        """
        today = clock.today()
        for year in sorted(wanted):
            if year > today.year or year in with_papers:
                continue
            message = f"{self.council_name}: no Council meetings with papers in {year}"
            if year == today.year and today - datetime.date(
                year, 1, 1
            ) > datetime.timedelta(days=90):
                raise RuntimeError(message + "; the listing has probably changed")
            self.logger.warning(message)

    def scraper(self) -> list[ScraperReturn]:
        """Waits its turn on a shared server, then reads the council.

        A whole run holds the turn, rather than each request, so the councils
        waiting behind it are not also holding requests half-done: the
        server's time is the same either way, and the first in line finishes
        in its own time rather than everyone finishing at the end.
        """
        lock = _backend_lock(self._backend_key())
        started = time.monotonic()
        if not lock.acquire(timeout=MAX_TURN_WAIT_SECONDS):
            raise TimeoutError(
                f"{self.council_name}: waited {MAX_TURN_WAIT_SECONDS:.0f} s for "
                f"its turn on {self._backend_key()}; giving up so the run "
                f"stays inside its budget"
            )
        try:
            waited = time.monotonic() - started
            if waited > 1:
                self.logger.info(
                    f"{self.council_name}: waited {waited:.0f} s for "
                    f"{self._backend_key()}"
                )
            return self._scrape()
        finally:
            lock.release()

    def _scrape(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        today = clock.today()
        horizon = today + datetime.timedelta(days=UPCOMING_WINDOW_DAYS)

        documents: list[DatascapeDocument] = []
        offered: Optional[set[int]] = None
        for year in sorted(wanted):
            if offered and year not in offered:
                continue
            items, offered_now = self._listing(year)
            if offered is None:
                offered = offered_now
                if offered and year not in offered:
                    # The site answers an unoffered year with its default
                    # view, which is not that year.
                    continue
            failed = fetched = 0
            for item in items:
                if not self._keeps(item):
                    continue
                listed = item.listed_date
                if listed is not None and listed > horizon:
                    continue
                fetched += 1
                try:
                    documents.extend(self._documents(item))
                except Exception as error:
                    failed += 1
                    self.logger.warning(
                        f"{self.council_name}: item {item.url} ({item.title!r}) "
                        f"failed: {type(error).__name__}: {error}"
                    )
            if fetched and failed == fetched:
                raise RuntimeError(
                    f"{self.council_name}: every item page for {year} failed"
                )

        results = []
        for (body, date), group in sorted(
            self._group(documents).items(), key=lambda kv: (kv[0][1], kv[0][0])
        ):
            if date.year not in wanted:
                continue
            meeting = self._meeting(body, date, group)
            if meeting is not None:
                results.append(meeting)

        self._check_years_have_meetings(
            wanted, {datetime.date.fromisoformat(r.date).year for r in results}
        )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
