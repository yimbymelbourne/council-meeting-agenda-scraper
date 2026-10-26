"""Moorabool Shire Council—OpenCities content pages, a page per year.

The landing page, /About-Council/Councillors/Agendas-and-Minutes, links
this year's two pages—"Ordinary Meetings of Council - 2026" and "Council
Committees - 2026"—and two index pages, "Agendas and Minutes - Previous
Years" and "Committee Agenda and Minutes - Previous Years", which link a
page per earlier year. The links point at four generations of path
(/Councillors/Council-meetings/..., /Councillors-and-meetings/...,
/Council-meetings/...) that redirect to the pages' current addresses, so
the year is read from the end of the link and the link is followed rather
than the address built.

Each year page is a list of panels (``div.oc-wysiwyg-container-panel``),
one per meeting, headed by its date with or without the year ("4 February",
"18 March 2026"). Inside are the papers, labelled by what they are:
"Agenda", "Attachments", "Minutes", "SMC Agenda", "Agenda - Statutory
Meeting of Council", plus livestream links and agenda highlights. The
panel is the meeting, so papers are paired by the panel and never by their
filenames, which are typed by hand: the 15 July 2026 Development Assessment
Committee agenda is "agenda_dac_17-july-2026.pdf", the 26 June 2024
special meeting's minutes are "...-29-june-2024.pdf".

The committee pages before 2025 are laid out the other way round: a panel
per committee, headed by its name, with each meeting's date on a line of its
own ("<p><strong>15 February</strong></p>") above its papers. Both layouts
are read by walking the page in order, keeping the last body name and the
last date seen.

What a Council meeting is called comes from its papers, because the council
page names none: "OMC" (Ordinary), "SMC" (Special), "UMC" (Unscheduled),
"StatMC" (Statutory), in the link text, the link's title or its filename.
Since mid-2025 a meeting called outside the schedule is an Unscheduled
Meeting of Council, but some of its files are still named "smc": the 15
April 2026 agenda is "agenda-smc-15-april-2026.pdf" and its first page
reads "Unscheduled Council Meeting" (checked 26 Oct 2026), so a panel
naming either "unscheduled" or "UMC" anywhere is one.

Many papers from 2020 to 2022 are Word files only. A Word agenda or minutes
goes in ``agenda_html_url``/``minutes_html_url``, as `augusta_margaret_river`
and Kwinana do, because the PDF fields promise a PDF; a PDF of the same
paper wins over it.

A production year is the landing page and this year's two pages: three
requests, 4.7 s (26 Oct 2026, home connection). robots.txt sets no
Crawl-delay.
"""

from __future__ import annotations

import calendar
import datetime
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

# A documented robots.txt exception. www.moorabool.vic.gov.au/robots.txt
# (checked 26 Oct 2026) has, for `User-agent: *`:
#
#     Disallow: /About-Council/Councillors/Agendas-and-Minutes/*
#     Disallow: /About-Council/Councillors/Council-meetings/*
#     Disallow: /About-Council/Councillors-and-meetings/Council-meetings/*
#     Disallow: /About-Council/Council-meetings/*
#
# and every year page lives under the first, reached through links under
# the other three. The landing page itself, /About-Council/Councillors/
# Agendas-and-Minutes, has no trailing slash and is not disallowed. The
# maintainer decided on 26 Oct 2026 to read the year pages anyway, as for
# `swan`, because these papers are the council's official public record.
# The papers (/files/...) are not disallowed, and nothing else is read.
# robots.txt sets no Crawl-delay.

_SITE = "https://www.moorabool.vic.gov.au"
_LANDING = f"{_SITE}/About-Council/Councillors/Agendas-and-Minutes"

# "Ordinary-Meetings-of-Council-2026", "Agendas-and-Minutes-2025",
# "Agenda-and-Minutes-2024", "Council-Committees-2026".
_YEAR_PAGE = re.compile(
    r"/(?P<kind>Ordinary-Meetings-of-Council|Agendas?-and-Minutes|Council-Committees)"
    r"-(?P<year>20\d\d)$",
    re.IGNORECASE,
)
_PREVIOUS_YEARS = re.compile(
    r"/(?:Committee-)?Agendas?-and-Minutes-Previous-Years$", re.IGNORECASE
)

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
# A panel heading or a date line: "4 February", "18 March 2026",
# "1 April - Ballan" (a 2020 meeting's venue). A heading with no day
# ("October", 2020, no papers) is not a meeting.
_DATE = re.compile(
    r"^(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]{3,9})\b"
    r"(?:,?\s+(?P<year>20\d\d))?(?:\s*-\s*[A-Za-z ]+)?$"
)
# "December 2022": a committee meeting dated by its month only (2022). Its
# day is taken from a paper's title or filename naming that month
# ("agenda-moorabool-growth-management-committee-7-december.pdf"), and
# without one the meeting is left out; a day is never invented.
_MONTH_ONLY = re.compile(r"^(?P<month>[A-Za-z]{3,9})\s+(?P<year>20\d\d)$")
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\b")

# What a link is, read from its own text. The agenda's attachment book is
# "Attachments" or "Agenda Attachments"; an item's papers are "Item 12.1 -
# Attachment 1 - ..." or "OMC Attachment - Item 14.1"; "SMC Minutes -
# Attachment" is the adopted budget. None is the agenda or the minutes.
_NOT_THE_PAPER = re.compile(
    r"\battachments?\b|\bappendi|\baddend|\bsupplementary\b|\blate\b|\bitem\b"
    r"|\bhighlights?\b|\baudio\b|\bpresentation\b",
    re.IGNORECASE,
)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_PDF = ".pdf"
_WORD = (".docx", ".doc")

# The meeting types, as the council's labels, titles and filenames abbreviate
# them. Checked in this order: see the module docstring for why Unscheduled
# outranks Special.
_COUNCIL_TYPES = (
    (
        re.compile(r"unscheduled|\bumc\b", re.IGNORECASE),
        "Unscheduled Meeting of Council",
    ),
    (
        re.compile(r"statutory|\bstatmc\b", re.IGNORECASE),
        "Statutory Meeting of Council",
    ),
    (re.compile(r"special|\bsmc\b", re.IGNORECASE), "Special Meeting of Council"),
    (re.compile(r"ordinary|\bomc\b", re.IGNORECASE), "Ordinary Meeting of Council"),
)
_NOT_A_BODY = re.compile(
    r"related information|ordinary meetings of council", re.IGNORECASE
)


@dataclass
class _Meeting:
    date: Optional[datetime.date]
    body: Optional[str]
    page_url: str
    # (year, month) for a meeting headed by its month only.
    month: Optional[tuple[int, int]] = None
    # (kind, url, filename)
    papers: list[tuple[str, str, str]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def _is_committees(url: str) -> bool:
    return "committee" in urlparse(url).path.lower()


def _words(text: str) -> str:
    """Filename separators as spaces, so `\\bsmc\\b` matches "agenda-smc-..."."""
    return re.sub(r"[_\-.]+", " ", text)


@register_scraper
class MooraboolScraper(BaseScraper):
    # One production year (the landing page and 2026's two pages) took 4.7 s
    # from a home connection on 26 Oct 2026, under the 5 s default, so
    # `expected_seconds` is left alone.

    def __init__(self):
        super().__init__("moorabool", "VIC", _LANDING)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    # --- what to fetch ------------------------------------------------------

    @staticmethod
    def _links(html: str, base: str) -> tuple[dict[str, int], list[str]]:
        """Year pages ({url: year}) and previous-years indexes a page links."""
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("#main-content") or soup
        years: dict[str, int] = {}
        indexes: list[str] = []
        for a in content.find_all("a", href=True):
            url = urljoin(base, a["href"]).split("#")[0].split("?")[0]
            path = urlparse(url).path.rstrip("/")
            m = _YEAR_PAGE.search(path)
            if m:
                years.setdefault(url, int(m["year"]))
            elif _PREVIOUS_YEARS.search(path) and url not in indexes:
                indexes.append(url)
        # One page per year and kind. The index links 2021's council page
        # twice, by two of its old paths, which redirect to the same page.
        first: dict[tuple[bool, int], str] = {}
        for url, year in years.items():
            first.setdefault((_is_committees(url), year), url)
        return {url: years[url] for url in first.values()}, indexes

    def _year_pages(self, wanted: set[int]) -> dict[str, int]:
        landing = self.fetcher.fetch_with_requests(_LANDING)
        pages, indexes = self._links(landing, _LANDING)
        if not pages:
            raise RuntimeError(f"moorabool: no year pages linked from {_LANDING}")
        latest = max(pages.values())
        # Earlier years are only on the two previous-years indexes: read them
        # only for a run that asks for one.
        if any(year < latest for year in wanted):
            if not indexes:
                raise RuntimeError(f"moorabool: no previous-years index on {_LANDING}")
            for index in indexes:
                found, _ = self._links(self.fetcher.fetch_with_requests(index), index)
                taken = {(_is_committees(u), y) for u, y in pages.items()}
                for url, year in found.items():
                    if (_is_committees(url), year) not in taken:
                        pages[url] = year
        return {url: year for url, year in pages.items() if year in wanted}

    # --- reading a page -----------------------------------------------------

    @staticmethod
    def _date(text: str, page_year: int) -> Optional[datetime.date]:
        m = _DATE.match(" ".join(text.split()))
        if not m:
            return None
        month = _MONTHS.get(m["month"][:3].lower())
        if not month:
            return None
        try:
            return datetime.date(int(m["year"] or page_year), month, int(m["day"]))
        except ValueError:
            return None

    def _meetings(self, html: str, page_url: str, page_year: int) -> list[_Meeting]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("#main-content")
        if content is None:
            raise RuntimeError(f"moorabool: no #main-content on {page_url}")
        committees = _is_committees(page_url)
        body: Optional[str] = None
        meetings: list[_Meeting] = []
        current: Optional[_Meeting] = None
        for el in content.find_all(["h2", "h3", "p", "strong", "a"]):
            if el.name in ("h2", "h3"):
                text = el.get_text(" ", strip=True)
                date = self._date(text, page_year)
                if date:
                    current = _Meeting(date, body, page_url)
                    meetings.append(current)
                elif text:
                    current = None
                    if not _NOT_A_BODY.search(text):
                        body = text if committees else None
                continue
            if el.name in ("p", "strong"):
                # A date on a line of its own, or in bold at the start of the
                # line holding its papers (committee pages to 2024). A line
                # is read by its <strong> where it has one.
                if el.find_parent("a"):
                    continue
                if el.name == "p" and (el.find("a") or el.find("strong")):
                    continue
                text = " ".join(el.get_text(" ", strip=True).split())
                date = self._date(text, page_year)
                month = _MONTH_ONLY.match(text)
                if date:
                    current = _Meeting(date, body, page_url)
                    meetings.append(current)
                elif month and _MONTHS.get(month["month"][:3].lower()):
                    current = _Meeting(
                        None,
                        body,
                        page_url,
                        month=(int(month["year"]), _MONTHS[month["month"][:3].lower()]),
                    )
                    meetings.append(current)
                continue
            if el.get("href"):
                self._paper(el, current, page_url)
        kept = []
        for meeting in meetings:
            if not meeting.papers:
                continue
            if meeting.date is None:
                self.logger.info(
                    f"moorabool: leaving out {meeting.body} {meeting.month}: "
                    f"no paper gives its day"
                )
                continue
            kept.append(meeting)
        return kept

    def _paper(self, a: Tag, meeting: Optional[_Meeting], page_url: str) -> None:
        url = urljoin(page_url, a["href"].strip())
        path = urlparse(url).path
        if "/files/" not in path:
            return
        info = a.select_one(".file-info")
        if info:
            info.extract()
        label = " ".join(a.get_text(" ", strip=True).split())
        filename = unquote(path.rsplit("/", 1)[-1])
        if meeting is None:
            if label:
                self.logger.info(f"moorabool: {label!r} ({filename}) is under no date")
            return
        text = " ".join([label, a.get("title", ""), _words(filename)])
        meeting.texts.append(text)
        if meeting.date is None and meeting.month:
            year, month = meeting.month
            days = {
                int(day)
                for day, name in _DAY_MONTH.findall(text)
                if _MONTHS.get(name[:3].lower()) == month
            }
            if len(days) == 1:
                try:
                    meeting.date = datetime.date(year, month, days.pop())
                except ValueError:
                    pass
        if not filename.lower().endswith((_PDF,) + _WORD):
            return
        if not label or _NOT_THE_PAPER.search(label):
            return
        agenda, minutes = bool(_AGENDA.search(label)), bool(_MINUTES.search(label))
        if agenda == minutes:
            return
        meeting.papers.append(("agenda" if agenda else "minutes", url, filename))

    # --- one record per meeting ---------------------------------------------

    def _name(self, meeting: _Meeting) -> str:
        if meeting.body:
            return re.sub(r"\s+", " ", meeting.body).strip()
        text = " ".join(meeting.texts)
        for pattern, name in _COUNCIL_TYPES:
            if pattern.search(text):
                return name
        return "Ordinary Meeting of Council"

    @staticmethod
    def _pick(papers: list[tuple[str, str, str]], kind: str):
        """(pdf url, word url) for one kind; the first of each is kept."""
        pdf = next(
            (u for k, u, f in papers if k == kind and f.lower().endswith(_PDF)), None
        )
        word = next(
            (u for k, u, f in papers if k == kind and f.lower().endswith(_WORD)), None
        )
        return pdf, (None if pdf else word)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        pages = self._year_pages(wanted)
        today = clock.today()
        missing = sorted(
            y
            for y in wanted
            if y not in pages.values()
            and (y < today.year or (y == today.year and today.month > 3))
        )
        if missing:
            # The landing page or an index no longer leads to a year that
            # has to exist. main.py would count a short list as a working
            # council, so fail.
            raise RuntimeError(f"moorabool: no page for {missing} from {_LANDING}")

        results: list[ScraperReturn] = []
        for url, year in pages.items():
            html = self.fetcher.fetch_with_requests(url)
            meetings = self._meetings(html, url, year)
            if not meetings and year < today.year:
                raise RuntimeError(f"moorabool: no meeting papers on {url}")
            for meeting in meetings:
                if meeting.date.year not in wanted:
                    continue
                agenda, agenda_word = self._pick(meeting.papers, "agenda")
                minutes, minutes_word = self._pick(meeting.papers, "minutes")
                if not (agenda or agenda_word or minutes or minutes_word):
                    continue
                results.append(
                    ScraperReturn(
                        name=self._name(meeting),
                        date=meeting.date.isoformat(),
                        time=None,
                        webpage_url=url,
                        agenda_url=agenda,
                        minutes_url=minutes,
                        agenda_html_url=agenda_word,
                        minutes_html_url=minutes_word,
                        download_url=agenda or minutes,
                    )
                )
        results.sort(key=lambda r: (r.date, r.name), reverse=True)
        if not results:
            self.logger.warning(f"moorabool: no meetings in {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
