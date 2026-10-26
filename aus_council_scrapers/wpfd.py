"""Council meeting papers published with WP File Download, a WordPress plugin.

WP File Download (JoomUnited; markup classes `wpfd-*`) files documents in
categories and renders each category as a list of links of the form

    /download/<category id>/<category slug>/<file id>/<file name>.pdf

with the file's title in the link's `title` attribute. The URL serves the
PDF itself (`Content-Disposition: attachment`), so it is the document URL to
store. Four north-west Tasmanian councils publish their papers this way:
Devonport, Central Coast, Waratah-Wynyard and West Coast.

Each council files them a little differently, which is why this base class
reads every file on its own rather than trusting the category:

- **One category per meeting** (Waratah-Wynyard, Central Coast, Devonport's
  archive). The slug usually names the date ("meeting-19-october-2026"), but
  not always ("15-april" with no year, "march-2024-agenda-and-minutes"), and
  one category can hold two meetings: Central Coast files the AGM and the
  ordinary meeting of 15 December 2025 together.
- **One category per month** (Devonport's current year, West Coast). The
  category says only "september-2026", so the day has to come from the file.

So each file gets a kind (agenda or minutes, from its title), a meeting type
(Council, AGM, special, planning, from its title and filename) and a date. The
date is voted on: the category's date, if it names one, and the date each
agenda and minutes file's title or filename names. The date most of them name
wins, the category winning a tie. Waratah-Wynyard needs that: its 20 July 2026
category holds "Council Muinutes 20 July 2027", and its 20 October 2025
category holds a copy of the 16 February 2026 agenda. A file outvoted at least
two to one is taken off the meeting only when the listing has a meeting of its
own on the date the file names, as `ionata.reconcile_date` does for the same
problem. Otherwise it is most likely this meeting's under a typo.

A meeting whose files name no day, in a category that names none either, is
left out with a warning rather than given an invented one. A subclass that
can learn the day from the council's own published schedule overrides
`undated_meeting_date` (West Coast).

Files that are neither the agenda nor the minutes are skipped: attachments,
appendices, supplementary and late items, single agenda items, audio
recordings (one of which Central Coast uploaded as a .pdf), annual reports.

The listing pages are static HTML, one or two requests per council. A
category whose files the plugin lazy-loads over admin-ajax has no links in
the page, only a placeholder link naming the category. On these four councils
that is only years before 2020, except West Coast's 2024 and 2025, whose files
name no day anyway. A placeholder naming a wanted year fails the scrape: it
means the council has started lazy-loading meetings this class would
otherwise quietly miss.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

_DOWNLOAD_PATH = re.compile(r"/download/(\d+)/([^/]+)/(\d+)/([^/?#]+)$")

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
# Full names first so "june" is not read as "jun" with "e" left over.
_MONTH_PATTERN = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
)

# "19 October 2026", "15th-february-2021", "8-Dec-2025", "10-sept-18" and
# Waratah-Wynyard's "05 November 25". A two-digit year is only taken where
# nothing four-digit follows it.
_DAY_MONTH_YEAR = re.compile(
    rf"(?<![\d])(\d{{1,2}})(?:st|nd|rd|th)?[\s_,-]+({_MONTH_PATTERN})"
    rf"[\s_,-]+(\d{{4}}|\d{{2}})(?!\d)",
    re.IGNORECASE,
)
# Day-first numerals, as AGM files are named: "2022 - AGM Agenda 24 10 2022",
# "2023-agm-agenda-15-01-24.pdf".
_NUMERIC_DATE = re.compile(
    r"(?<![\d.])(\d{1,2})[\s._-](\d{1,2})[\s._-](20\d\d|\d\d)(?![\d.])"
)
# "september-2026", "2024-april", "Agenda - March 2026": a month with no day.
_MONTH_YEAR = re.compile(
    rf"(?<![a-z])({_MONTH_PATTERN})[\s_,-]+(20\d\d)(?!\d)|(?<!\d)(20\d\d)[\s_,-]+({_MONTH_PATTERN})(?![a-z])",
    re.IGNORECASE,
)

# Anything that is not the meeting's agenda or minutes, whatever else its
# title says: "Agenda Attachment - Item 10.11", "Appendix 1 - Minutes of the
# Annual General Meeting Held 3 November 2020", "Supplementary Agenda Item
# 4.1", "Council Agenda 16 May 2022 - LATE ITEMS", "6.03.3 Current and
# Previous Minutes Resolutions", "Audio recording - Special Council Meeting".
_NOT_THE_PAPER = re.compile(
    r"attach|appendix|audio|recording|supplementary|late[\s_-]+(?:report|item)"
    r"|\bitems?\b|annual[\s_-]+report|questions?[\s_-]+on[\s_-]+notice"
    r"|^\s*\d+(?:\.\d+)+",
    re.IGNORECASE,
)
# An audio recording's title often names the meeting type when the papers do
# not: Central Coast's 25 May 2020 agenda and minutes say only "Council
# Meeting", its audio "Audio recording - Special Council Meeting".
_AUDIO = re.compile(r"audio|recording", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
# "MInutes", and Waratah-Wynyard's "Council Muinutes".
_MINUTES = re.compile(r"mu?inutes", re.IGNORECASE)
# A title that names only the body and the date, with no word for the
# document: "Planning Authority Committee - 2 June 2025 (1)". Both such files
# on Devonport's PAC page are the agenda (the PDF opens "NOTICE OF MEETING");
# the minutes are always labelled, being written afterwards. So one is used
# as the agenda, but only for a meeting that has no labelled agenda.
_BARE_MEETING_TITLE = re.compile(r"meeting|committee|council", re.IGNORECASE)
_NOT_A_MEETING_PAPER = re.compile(r"report|policy|plan\b|strategy", re.IGNORECASE)
# Minutes the council itself marks as not yet adopted. Kept, but a confirmed
# copy of the same minutes wins over them.
_PROVISIONAL = re.compile(r"unconfirmed|draft", re.IGNORECASE)

# The meeting type, read from the file's title and filename. Planning bodies
# are on listings of their own on these sites, so the listing's
# `default_name` names them in the body's own words ("Planning Authority
# Committee", "Planning Sub-Committee") rather than a rule here.
DEFAULT_NAME_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(r"annual[\s_-]+general|\bagm\b", re.IGNORECASE),
        "Annual General Meeting",
    ),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Council Meeting"),
)


def _month_number(name: str) -> int:
    name = name.lower()
    return next(
        i for i, full in enumerate(_MONTH_NAMES, 1) if full.startswith(name[:3])
    )


def _make_date(year: int, month: int, day: int) -> Optional[datetime.date]:
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def find_date(text: str) -> Optional[datetime.date]:
    """The first full date written in `text`, with a month name or as numerals."""
    if m := _DAY_MONTH_YEAR.search(text):
        day, month, year = m.groups()
        return _make_date(int(year), _month_number(month), int(day))
    if m := _NUMERIC_DATE.search(text):
        day, month, year = m.groups()
        return _make_date(int(year), int(month), int(day))
    return None


def find_month(text: str) -> Optional[tuple[int, int]]:
    """A (year, month) written in `text` without a day, if any."""
    m = _MONTH_YEAR.search(text)
    if not m:
        return None
    month, year = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return int(year), _month_number(month)


def find_year(text: str) -> Optional[int]:
    """The year `text` names, as a full date, a month or a bare year."""
    if date := find_date(text):
        return date.year
    if month := find_month(text):
        return month[0]
    if m := _YEAR.search(text):
        return int(m.group(1))
    return None


@dataclass(frozen=True)
class WPFDListing:
    """One page of WPFD categories."""

    url: str
    # What a meeting is called when its files say nothing more specific:
    # "Council Meeting" on the council's page, the committee's name on a
    # committee's page, whose files rarely repeat it.
    default_name: str = "Council Meeting"
    # A page holding only past years. It is fetched only when a year before
    # the current one is wanted, so a one-year production run skips it.
    archive: bool = False


@dataclass
class WPFDFile:
    url: str
    file_id: int
    category_id: int
    category_slug: str
    title: str
    listing: WPFDListing
    kind: str  # "agenda", "minutes" or "unlabelled"
    name: str
    own_date: Optional[datetime.date]


@dataclass
class _Meeting:
    name: str
    date: datetime.date
    listing: WPFDListing
    files: list[WPFDFile] = field(default_factory=list)


class WPFileDownloadScraper(BaseScraper):
    listings: tuple[WPFDListing, ...]
    name_rules: tuple[tuple[re.Pattern, str], ...] = DEFAULT_NAME_RULES
    # The first year the council's papers can be dated to the day. Later than
    # EARLIEST_YEAR only where earlier years are known to be undatable (West
    # Coast), so asking for them returns nothing instead of failing.
    earliest_year: int = EARLIEST_YEAR

    # --- hooks ----------------------------------------------------------

    def listing_times(
        self, listing: WPFDListing, soup: BeautifulSoup
    ) -> dict[datetime.date, str]:
        """Start times the listing page itself publishes, by meeting date.

        Empty by default. Applied only to meetings of the listing's
        `default_name`, since a page's schedule of dates is its ordinary
        meetings' (Devonport).
        """
        return {}

    def meeting_name(self, title: str, filename: str, listing: WPFDListing) -> str:
        text = f"{title} {filename}"
        for pattern, name in self.name_rules:
            if pattern.search(text):
                return name
        return listing.default_name

    def undated_meeting_date(
        self, month: Optional[tuple[int, int]], name: str, files: list[WPFDFile]
    ) -> Optional[datetime.date]:
        """The day of a meeting whose files and category name only a month.

        None by default: such a meeting is left out rather than given a day
        nobody published. `month` is the (year, month) the category or the
        files name, if they name one.
        """
        return None

    # --- years ----------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        years = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        return {y for y in years if y >= self.earliest_year}

    # --- parsing --------------------------------------------------------

    def _classify(self, title: str, filename: str) -> Optional[str]:
        text = title or filename
        if _NOT_THE_PAPER.search(text):
            return None
        agenda = _AGENDA.search(text)
        minutes = _MINUTES.search(text)
        if agenda and minutes:
            # Neither title seen on these sites says both; if one does, the
            # word it leads with is the document ("Minutes ... Agenda Item").
            return "agenda" if agenda.start() < minutes.start() else "minutes"
        if agenda:
            return "agenda"
        if minutes:
            return "minutes"
        if _BARE_MEETING_TITLE.search(text) and not _NOT_A_MEETING_PAPER.search(text):
            return "unlabelled"
        return None

    def _parse_listing(
        self, listing: WPFDListing, soup: BeautifulSoup, wanted: set[int]
    ) -> list[WPFDFile]:
        files: list[WPFDFile] = []
        linked_categories: set[int] = set()
        # The meeting types the category's audio recordings name.
        audio_names: dict[int, set[str]] = {}
        for link in soup.select("a[href*='/download/']"):
            url = urljoin(listing.url, link["href"].strip())
            m = _DOWNLOAD_PATH.search(urlparse(url).path)
            if not m:
                continue
            category_id, category_slug, file_id, filename = m.groups()
            linked_categories.add(int(category_id))
            filename = unquote(filename)
            title = " ".join(
                (link.get("title") or link.get_text(" ", strip=True)).split()
            )
            stem = filename.rsplit(".", 1)[0]
            if _AUDIO.search(title or filename):
                audio_names.setdefault(int(category_id), set()).add(
                    self.meeting_name(title, stem, listing)
                )
            if not filename.lower().endswith(".pdf"):
                continue
            kind = self._classify(title, filename)
            if kind is None:
                continue
            files.append(
                WPFDFile(
                    url=url,
                    file_id=int(file_id),
                    category_id=int(category_id),
                    category_slug=category_slug,
                    title=title,
                    listing=listing,
                    kind=kind,
                    name=self.meeting_name(title, stem, listing),
                    own_date=find_date(title) or find_date(stem),
                )
            )
        if not linked_categories:
            # A WPFD listing always carries download links. None at all means
            # the page or the plugin's markup changed, and returning nothing
            # would read as a council with no meetings.
            raise ValueError(
                f"{self.council_name}: no WP File Download links on {listing.url}"
            )

        # A category the plugin lazy-loads appears only as a placeholder link
        # (`a.catlink[data-idcat]`) whose files are fetched by the browser
        # over admin-ajax. One naming a wanted year means meetings this
        # scrape cannot see, so fail rather than return a short list.
        lazy = []
        for placeholder in soup.select("a.catlink[data-idcat]"):
            try:
                category_id = int(placeholder["data-idcat"])
            except ValueError:
                continue
            label = placeholder.get("title") or placeholder.get_text(" ", strip=True)
            if category_id not in linked_categories and find_year(label) in wanted:
                lazy.append(label)
        if lazy:
            raise ValueError(
                f"{self.council_name}: {listing.url} lazy-loads categories for "
                f"wanted years, whose files are not in the page: {', '.join(lazy)}"
            )

        # A one-meeting category (its slug names a full date) whose papers
        # name no type more specific than the listing's takes the type its
        # audio recordings agree on. Not month categories, where the audio
        # may be another meeting's that month.
        by_category: dict[int, list[WPFDFile]] = {}
        for f in files:
            by_category.setdefault(f.category_id, []).append(f)
        for category_id, group in by_category.items():
            names = audio_names.get(category_id, set())
            if (
                len(names) == 1
                and find_date(group[0].category_slug) is not None
                and all(f.name == listing.default_name for f in group)
            ):
                (name,) = names
                if name != listing.default_name:
                    for f in group:
                        f.name = name
        return files

    def _month_category_date(
        self, f: WPFDFile, category_month: Optional[tuple[int, int]]
    ) -> Optional[datetime.date]:
        """A dated file's date, checked against its month category.

        In a month category the file is the only witness to the date, so a
        typo in it would make a meeting of its own. The councils make one
        kind ("Council Muinutes 20 July 2027" in Waratah-Wynyard's July 2026
        meeting): the right day and month in the wrong year. That one is
        corrected to the category's year. A file naming another month is
        left out with a warning, since nothing says which of the two is wrong.
        """
        date = f.own_date
        if date is None or category_month is None:
            return date
        year, month = category_month
        if (date.year, date.month) == (year, month):
            return date
        if date.month == month:
            corrected = _make_date(year, month, date.day)
            self.logger.warning(
                f"{self.council_name}: {f.title!r} in category "
                f"{f.category_slug!r} names {date}; taken as {corrected}"
            )
            return corrected
        self.logger.warning(
            f"{self.council_name}: {f.title!r} in category {f.category_slug!r} "
            f"names {date}, another month; left out"
        )
        return None

    def _group(self, files: list[WPFDFile], wanted: set[int]) -> list[_Meeting]:
        by_category: dict[tuple[int, str], list[WPFDFile]] = {}
        for f in files:
            by_category.setdefault((f.category_id, f.name), []).append(f)

        meetings: list[_Meeting] = []
        # (category, name) groups whose files outvoted at least two to one
        # name another date; settled once every meeting's date is known.
        disputed: list[tuple[_Meeting, WPFDFile]] = []
        for (category_id, name), group in by_category.items():
            slug = group[0].category_slug
            category_date = find_date(slug)
            listing = group[0].listing
            if category_date is None:
                # A month category (or a slug with no year): every dated file
                # is its own meeting's, and the undated ones share one.
                category_month = find_month(slug)
                undated = [f for f in group if f.own_date is None]
                by_date: dict[datetime.date, list[WPFDFile]] = {}
                for f in group:
                    if f.own_date is not None:
                        date = self._month_category_date(f, category_month)
                        if date is not None:
                            by_date.setdefault(date, []).append(f)
                for date, dated in by_date.items():
                    meetings.append(_Meeting(name, date, listing, dated))
                if undated:
                    month = category_month or next(
                        (m for f in undated if (m := find_month(f.title))), None
                    )
                    if month is not None and month[0] not in wanted:
                        # Not asked for, so not worth a schedule lookup or a
                        # warning.
                        continue
                    date = self.undated_meeting_date(month, name, undated)
                    if date is None:
                        self.logger.warning(
                            f"{self.council_name}: {name} in category {slug!r} "
                            f"({', '.join(f.title for f in undated)}) names no day; "
                            f"left out"
                        )
                        continue
                    meetings.append(_Meeting(name, date, listing, undated))
                continue

            votes = [category_date] + [f.own_date for f in group if f.own_date]
            counts = {d: votes.count(d) for d in votes}
            best = max(counts.values())
            chosen = (
                category_date
                if counts[category_date] == best
                else next(d for d in votes if counts[d] == best)
            )
            meeting = _Meeting(name, chosen, listing)
            for f in group:
                if (
                    f.own_date is not None
                    and f.own_date != chosen
                    and counts[chosen] >= 2 * counts[f.own_date]
                ):
                    disputed.append((meeting, f))
                else:
                    meeting.files.append(f)
            meetings.append(meeting)

        held_dates = {m.date for m in meetings if m.files}
        for meeting, f in disputed:
            if f.own_date in held_dates:
                self.logger.info(
                    f"{self.council_name}: {f.title!r} is filed under the "
                    f"{meeting.date} {meeting.name} but names {f.own_date}, "
                    f"which has a meeting of its own; left off"
                )
                continue
            meeting.files.append(f)
        # An unlabelled file alone is not evidence of a meeting's papers.
        return [
            m for m in meetings if any(f.kind in ("agenda", "minutes") for f in m.files)
        ]

    @staticmethod
    def _pick(meeting: _Meeting, kind: str) -> Optional[str]:
        """The one agenda or minutes for a meeting that may have several.

        A file whose own date is the meeting's beats one that only sits in
        its category; adopted minutes beat unconfirmed or draft ones; and
        among the rest the latest upload (highest file id) wins, since a
        re-upload ("-2.pdf", "(UPDATED)") replaces the one before it.
        """
        candidates = [f for f in meeting.files if f.kind == kind]
        if not candidates and kind == "agenda":
            candidates = [f for f in meeting.files if f.kind == "unlabelled"]
        if not candidates:
            return None
        best = max(
            candidates,
            key=lambda f: (
                f.own_date == meeting.date,
                not _PROVISIONAL.search(f.title),
                f.file_id,
            ),
        )
        return best.url

    # --- entry point ----------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        if not wanted:
            self.logger.info(
                f"{self.council_name}: nothing before {self.earliest_year} can "
                f"be dated to the day; no years to read"
            )
            return []
        need_archive = min(wanted) < clock.current_year()

        files: dict[int, WPFDFile] = {}
        times: dict[tuple[str, datetime.date], str] = {}
        for listing in self.listings:
            if listing.archive and not need_archive:
                continue
            soup = BeautifulSoup(
                self.fetcher.fetch_with_requests(listing.url), "html.parser"
            )
            for f in self._parse_listing(listing, soup, wanted):
                # The current page and the archive overlap for a year or so;
                # the file id is the same on both.
                files.setdefault(f.file_id, f)
            for date, time in self.listing_times(listing, soup).items():
                times[(listing.url, date)] = time

        merged: dict[tuple[str, datetime.date], _Meeting] = {}
        for meeting in self._group(list(files.values()), wanted):
            if meeting.date.year not in wanted:
                continue
            key = (meeting.name, meeting.date)
            if key in merged:
                merged[key].files.extend(meeting.files)
            else:
                merged[key] = meeting

        results = []
        for meeting in sorted(merged.values(), key=lambda m: (m.date, m.name)):
            agenda_url = self._pick(meeting, "agenda")
            minutes_url = self._pick(meeting, "minutes")
            results.append(
                ScraperReturn(
                    name=meeting.name,
                    date=meeting.date.isoformat(),
                    time=(
                        times.get((meeting.listing.url, meeting.date))
                        if meeting.name == meeting.listing.default_name
                        else None
                    ),
                    webpage_url=meeting.listing.url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with documents for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
