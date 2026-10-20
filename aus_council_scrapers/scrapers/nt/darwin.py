import datetime
import json
import re
from typing import Optional
from urllib.parse import unquote, urlencode, urljoin

import pytz
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR, TIMEZONES_BY_STATE

_BASE_URL = "https://www.darwin.nt.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/agendas-and-minutes"

# The listing is a Drupal view—twelve meetings a page, newest first, with an
# exposed date-range filter. We read it through Drupal's own `/views/ajax`
# endpoint rather than the page itself: that returns the same rendered rows
# without the site's menus and footer, about 45 KB a page instead of 450 KB,
# which matters because the cassette stores every page in full and the whole
# history since 2020 is around 40 pages. The view name and display id are the
# ones the page itself registers in its drupalSettings.
_AJAX_URL = f"{_BASE_URL}/views/ajax"
_VIEW_PARAMS = {
    "_wrapper_format": "drupal_ajax",
    "view_name": "agendas_minutes",
    "view_display_id": "block_1",
}

# Every category is kept—Ordinary and Special Council plus the advisory
# committees. Paging is twelve meetings a request whatever the mix, so one
# production year costs about five requests either way.
#
# A meeting's file fields are labelled "Agendas", "Minutes" and
# "Attachments". The Agendas field also carries late items, additional items
# and attachment books, and the Minutes field carries reports "moved into
# open" and restricted minutes, so documents are picked by name: first one
# that calls itself an agenda (or minutes), and failing that—pre-2021 files
# are often just `open_ordinary_council_meeting_30_june_2020.pdf`—the first
# that is not obviously something else.
_AGENDA = re.compile(r"(?<![a-z])(?:agenda|agn)(?![a-z])", re.IGNORECASE)
_NOT_AGENDA = re.compile(
    r"late|additional|attachment|supplementary|addendum", re.IGNORECASE
)
_NOT_AGENDA_FALLBACK = re.compile(
    r"late|additional|attachment|supplementary|addendum|item|notice|letter"
    r"|presentation|register|report|moved|minutes|decision",
    re.IGNORECASE,
)
_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])", re.IGNORECASE)
_NOT_MINUTES = re.compile(r"restricted", re.IGNORECASE)
_NOT_MINUTES_FALLBACK = re.compile(
    r"agenda|mov(?:ed|ing)|decision|report|restricted|attachment|item",
    re.IGNORECASE,
)
# Ranked last, not excluded: "minutes ... moved into open" is sometimes the
# only minutes a confidential special meeting has.
_MOVED = re.compile(r"mov(?:ed|ing)", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<![a-z])confirmed", re.IGNORECASE)

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
# "13 May 2021", "8apr2020", "open_agenda_-_tuesday_24_november_2020",
# "Monday 21st September". The day must not be the tail of a longer number.
_DAY_MONTH = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_\-]*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"(?:[\s_\-,]*(\d{4}))?",
    re.IGNORECASE,
)
# "ord_20210427_agn_2490.pdf"
_COMPACT = re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)")

# Titles from before the 2021 site migration carry the date, an ordinal or a
# month: "2nd Ordinary Council Meeting - 24 November 2020", "8 April 2020
# Special Council Meeting", "Youth Advisory Committee - October 2020". None of
# that is part of the meeting type.
_TITLE_DATE = re.compile(
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
    r"\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+\d{4})?",
    re.IGNORECASE,
)
_TITLE_ORDINAL = re.compile(r"^\d+(?:st|nd|rd|th)\s+", re.IGNORECASE)
_TITLE_MONTH = re.compile(
    r"\s*[-–—]\s*(?:january|february|march|april|may|june|july|august"
    r"|september|october|november|december)(?:\s+\d{4})?$",
    re.IGNORECASE,
)

# The stamp error we correct for is a day or two: see _meeting_date.
_MAX_STAMP_SHIFT_DAYS = 3
# Every 2020 row whose papers can be checked is stamped early—45 of the 46
# dated ones by a day, the 23 April special meeting by two—so a 2020 row
# whose papers name no date of their own is moved a day too. (The exception,
# the 9 December 2020 history committee, names its date and so never reaches
# that fallback.) The five undated 2020 rows that publish papers were all
# checked against the PDFs and are each a day early: the Arts and Cultural
# committee of 11 February, 9 June, 21 July and 15 September, and the Youth
# committee of 9 July. From 2021 the error is ragged—rows re-entered after
# the migration are right, migrated ones are not—so an undated 2021 row
# keeps its stamp.
_UNDATED_SHIFT_BEFORE_YEAR = 2021

# The site's own upload error: the 21 July 2020 Arts and Cultural committee
# row links agenda_10.pdf and minutes_9.pdf, which are byte-identical copies
# of the 9 June meeting's agenda_9.pdf and minutes_8.pdf ("Tuesday, June 9
# 2020"). Nothing in the names gives it away, so they are listed here rather
# than published as the July meeting's papers; the row then has no papers
# and is skipped.
_MISFILED = {
    f"{_BASE_URL}/sites/default/files/old_7_agendas_and_minutes_files/agenda_10.pdf",
    f"{_BASE_URL}/sites/default/files/old_7_agendas_and_minutes_files/minutes_9.pdf",
}


def _dates_in(text: str, default_year: int) -> set[datetime.date]:
    found = set()
    for day, month, year in _DAY_MONTH.findall(text):
        try:
            found.add(
                datetime.date(
                    int(year or default_year), _MONTHS[month[:3].lower()], int(day)
                )
            )
        except ValueError:
            pass
    for year, month, day in _COMPACT.findall(text):
        try:
            found.add(datetime.date(int(year), int(month), int(day)))
        except ValueError:
            pass
    return found


def _dates_near(text: str, stamped: datetime.date) -> set[datetime.date]:
    found = _dates_in(text, stamped.year)
    if stamped.month == 12:
        # "Agenda 2 January" on a meeting stamped 31 December.
        found |= {d for d in _dates_in(text, stamped.year + 1) if d.month == 1}
    return found


def _meeting_date(
    stamped: datetime.date, evidence: list[str], filenames: list[str]
) -> datetime.date:
    """The meeting's date, correcting the stamp where the papers disagree.

    Meetings entered before the site's 2021 migration are stamped a day or two
    early—the 8 December 2020 Ordinary Council Meeting is listed as 7
    December, with documents named `..._8_december_2020.pdf`. (It reads like
    a local-midnight date converted to UTC once too often.) From mid-2021 the
    stamp and the papers agree.

    The file names are the best evidence: they were written when the paper
    was, while titles and link text were typed in later, sometimes copying
    the wrong stamp ("Agenda 7 June 2021" links rapsc_agenda_8_june_2021.pdf,
    and the PDF says Tuesday 8 June). So a single date a day or so after the
    stamp in the file names, which never name the stamp itself, is the
    meeting. Failing that, the same test runs over title, link text and file
    names together. Papers that name no date near the stamp at all fall back
    to _UNDATED_SHIFT_BEFORE_YEAR. Anything else—several later dates, or the
    stamp named alongside one—keeps the stamp.
    """

    def later(found: set[datetime.date]) -> set[datetime.date]:
        return {d for d in found if 0 < (d - stamped).days <= _MAX_STAMP_SHIFT_DAYS}

    in_files: set[datetime.date] = set()
    for name in filenames:
        in_files |= _dates_near(name, stamped)
    if stamped not in in_files and len(later(in_files)) == 1:
        return later(in_files).pop()

    found = set(in_files)
    for text in evidence:
        found |= _dates_near(text, stamped)
    if stamped in found:
        return stamped
    if len(later(found)) == 1:
        return later(found).pop()
    near = {d for d in found if abs((d - stamped).days) <= _MAX_STAMP_SHIFT_DAYS}
    if not near and stamped.year < _UNDATED_SHIFT_BEFORE_YEAR:
        return stamped + datetime.timedelta(days=1)
    return stamped


def _meeting_name(title: str) -> str:
    name = re.sub(r"\s+", " ", title).strip()
    name = _TITLE_DATE.sub("", name)
    name = _TITLE_ORDINAL.sub("", name.strip())
    name = re.sub(r"\s+", " ", name).strip(" -–—")
    name = _TITLE_MONTH.sub("", name).strip(" -–—")
    return name


@register_scraper
class DarwinScraper(BaseScraper):
    def __init__(self):
        super().__init__("darwin", "NT", _BASE_URL)
        self._timezone = pytz.timezone(TIMEZONES_BY_STATE["NT"])

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page_url(self, first: int, last: int, page: int) -> str:
        params = {
            **_VIEW_PARAMS,
            "field_agendas_date_value[min]": f"{first}-01-01",
            "field_agendas_date_value[max]": f"{last}-12-31",
            "page": page,
        }
        return f"{_AJAX_URL}?{urlencode(params)}"

    @staticmethod
    def _rows_html(body: str) -> str:
        """Pull the rendered view out of a Drupal AJAX response.

        The response is a list of commands; the view's markup is in the first
        `insert`. Drupal wraps the JSON in a `<textarea>` when the request did
        not come from its own XHR code, which ours does not.
        """
        match = re.search(r"<textarea>(.*)</textarea>", body, re.DOTALL)
        commands = json.loads(match.group(1) if match else body)
        for command in commands:
            if command.get("command") == "insert" and command.get("data"):
                return command["data"]
        return ""

    def _stamped_date(self, time_tag) -> Optional[datetime.date]:
        # "2026-09-29T12:00:00Z". Converted to Darwin time rather than cut at
        # the "T", so the date is the local one whatever hour gets stamped.
        try:
            stamp = datetime.datetime.fromisoformat(
                time_tag["datetime"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError):
            return None
        return stamp.astimezone(self._timezone).date()

    @staticmethod
    def _files(row, label: str) -> list[tuple[str, str]]:
        """(href, descriptive text) for each PDF in the field labelled `label`."""
        files = []
        for field in row.select(".field--type-file"):
            field_label = field.select_one(".field__label")
            if not field_label or field_label.get_text(strip=True) != label:
                continue
            for link in field.find_all("a", href=True):
                href = urljoin(_BASE_URL, link["href"])
                # A handful of 2020 committee papers are .docx; agenda_url and
                # minutes_url are for PDFs.
                if not href.lower().endswith(".pdf") or href in _MISFILED:
                    continue
                filename = unquote(href.rsplit("/", 1)[-1])
                files.append((href, f"{link.get_text(' ', strip=True)} {filename}"))
        return files

    @staticmethod
    def _for_this_meeting(
        files: list[tuple[str, str]], date: datetime.date, stamped: datetime.date
    ) -> list[tuple[str, str]]:
        """Drop documents that name some other meeting's date.

        The 4 March 2021 Access and Inclusion meeting carries "Unconfirmed
        Minutes 4 February 2021"—the previous meeting's—in its Minutes field.
        A document naming no date at all is kept, and only day and month are
        compared, because the year is the part most often mistyped: the 13
        October 2022 Youth Advisory Committee's minutes are filed as "Minutes
        13 October 2023".
        """
        own_days = {(date.month, date.day), (stamped.month, stamped.day)}
        kept = []
        for href, text in files:
            named = {(d.month, d.day) for d in _dates_near(text, stamped)}
            if named and not named & own_days:
                continue
            kept.append((href, text))
        return kept

    @staticmethod
    def _pick_agenda(files: list[tuple[str, str]]) -> Optional[str]:
        for href, text in files:
            if _AGENDA.search(text) and not _NOT_AGENDA.search(text):
                return href
        for href, text in files:
            if not _NOT_AGENDA_FALLBACK.search(text):
                return href
        return None

    @staticmethod
    def _pick_minutes(files: list[tuple[str, str]]) -> Optional[str]:
        candidates = [
            (bool(_MOVED.search(text)), not _CONFIRMED.search(text), i, href)
            for i, (href, text) in enumerate(files)
            if _MINUTES.search(text) and not _NOT_MINUTES.search(text)
        ]
        # Prefer real minutes over "moved into open" extracts, and confirmed
        # over unconfirmed when a meeting carries both; otherwise page order.
        if candidates:
            return min(candidates)[3]
        for href, text in files:
            if not _NOT_MINUTES_FALLBACK.search(text):
                return href
        return None

    def _parse_row(self, row) -> Optional[ScraperReturn]:
        time_tag = row.find("time")
        title_tag = row.find("h3")
        if not time_tag or not title_tag:
            return None
        stamped = self._stamped_date(time_tag)
        if stamped is None:
            return None

        title = title_tag.get_text(" ", strip=True)
        agendas = self._files(row, "Agendas")
        minutes = self._files(row, "Minutes")
        attachments = self._files(row, "Attachments")
        papers = agendas + minutes + attachments
        date = _meeting_date(
            stamped,
            [title] + [text for _, text in papers],
            [unquote(href.rsplit("/", 1)[-1]) for href, _ in papers],
        )

        agenda_url = self._pick_agenda(self._for_this_meeting(agendas, date, stamped))
        minutes_url = self._pick_minutes(
            self._for_this_meeting(minutes, date, stamped)
        )
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=_meeting_name(title),
            date=date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        # One date window spanning every wanted year: production asks for a
        # single year, and a single window has no year boundaries to page
        # across.
        first, last = min(wanted), max(wanted)

        results: list[ScraperReturn] = []
        page = 0
        while True:
            url = self._page_url(first, last, page)
            try:
                body = self.fetcher.fetch_with_requests(url)
                soup = BeautifulSoup(self._rows_html(body), "html.parser")
            except Exception as e:
                # The first page failing means the council is unreachable
                # (a block, an outage), and returning nothing would report
                # it as a working council with no meetings. Raise, so the
                # run records a failure. A later page failing still leaves
                # the newest meetings worth keeping.
                if page == 0:
                    raise
                self.logger.warning(
                    f"{self.council_name}: listing page {page} failed ({url}): {e}"
                )
                break

            rows = soup.select(".node-teaser-agendas")
            for row in rows:
                meeting = self._parse_row(row)
                if meeting and meeting.cleaned_date.year in wanted:
                    results.append(meeting)

            # The view's "Load More" link is the pager; it is absent on the
            # last page.
            if not rows or not soup.select_one("a[rel=next]"):
                break
            page += 1

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
