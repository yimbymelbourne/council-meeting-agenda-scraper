import datetime
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.lgasa import (
    CHALLENGE_WAIT_SECONDS,
    CRAWL_DELAY_SECONDS,
    DOCUMENT_ROOT,
)

_BASE_URL = "https://www.apc.sa.gov.au"

# Adelaide Plains is on LGA SA's shared Squiz Matrix platform, but not on
# its Funnelback collection: the page embeds the collection's listing and it
# reports "All results (0)", so `LGASAFunnelbackScraper` has nothing to
# read. The papers are instead in a static document list rendered into the
# page itself: one `<table id="2026">` per year (2013 onwards, every year on
# the one page), one row per meeting date ("Meeting Date: 21 October 2026"),
# and in each row one entry per document with its title and a category
# ("Agendas", "Minutes", "Late Item", "Attachments", "Confidential Item
# Released", "Video Recording", "Information").
#
# Two pages are read: Council meetings, and the Council Assessment Panel,
# the planning body, which has the same list. Production pays both page
# loads and one crawl delay between them.
_LISTINGS = (
    (f"{_BASE_URL}/our-council/meetings/council-meetings", None),
    (
        f"{_BASE_URL}/our-council/meetings/council-assessment-panel",
        "Council Assessment Panel",
    ),
)

# The category is right most of the time but not always ("Signed Minutes -
# Special Council Meeting - 30 June 2020" is filed under Agendas), so the
# title decides agenda or minutes, and the category only rules documents
# out. Late items, attachments, recordings and notices are never the agenda
# or minutes. Neither is a confidential item released later on its own.
_SKIPPED_CATEGORIES = frozenset(
    {
        "attachments",
        "confidential item released",
        "information",
        "late item",
        "video recording",
    }
)
_NOT_A_PAPER = re.compile(
    r"late item|notice|attachment|\bitem\b|recording", re.IGNORECASE
)
# "Release from Confidence - Minutes - ...", "Partial Release from
# Confidence - Agenda - ...": a meeting's own paper reissued with its
# confidential part released.
_RELEASE_PREFIX = re.compile(
    r"^\s*(?:partial\s+)?releas\w*\s+from\s+confidence\s*-\s*", re.IGNORECASE
)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_SIGNED = re.compile(r"\bsigned\b", re.IGNORECASE)
_DRAFT = re.compile(r"\bdraft\b", re.IGNORECASE)
_RELEASE = re.compile(r"releas", re.IGNORECASE)
# "Minutes - Reconvened Ordinary Council Meeting - 30 July 2025", "Minutes -
# Adjourned Ordinary Council Meeting - 23 February 2021": the second sitting
# of a meeting adjourned part-way, listed in a row under its own date. It is
# returned as a meeting of its own on that date, since that is where the
# council files it; the first sitting keeps its agenda (and its minutes,
# where it has any) on its own date. "Minutes - Special Council Meeting - 24
# June 2026 - Reconvened 1 July 2026" is filed the same way, under 1 July.
_RESUMED = re.compile(r"\b(reconvened|adjourned)\b", re.IGNORECASE)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
_ROW_DATE = re.compile(rf"(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})", re.IGNORECASE)
_ASSET = re.compile(r"/__data/assets/[^/]+/[^/]+/(\d+)/")


def _row_date(text: str) -> Optional[datetime.date]:
    match = _ROW_DATE.search(text)
    if not match:
        return None
    month = _MONTHS.split("|").index(match[2].lower()) + 1
    try:
        return datetime.date(int(match[3]), month, int(match[1]))
    except ValueError:
        return None


def _title_dates(title: str) -> list[datetime.date]:
    dates = []
    for match in _ROW_DATE.finditer(title):
        month = _MONTHS.split("|").index(match[2].lower()) + 1
        try:
            dates.append(datetime.date(int(match[3]), month, int(match[1])))
        except ValueError:
            continue
    return dates


def _meeting_name(title: str, body: Optional[str]) -> str:
    if body:
        return body
    lowered = title.lower()
    kind = (
        "Special Council Meeting"
        if "special" in lowered
        else "Ordinary Council Meeting" if "ordinary" in lowered else "Council Meeting"
    )
    resumed = _RESUMED.search(title)
    if resumed:
        return f"{resumed[1].capitalize()} {kind}"
    return kind


def _rank(kind: str, title: str) -> int:
    """Lower is better among one meeting's agendas or minutes.

    The signed minutes over the unsigned, then the plain paper over a later
    release of it, then a draft.
    """
    if kind == "minutes" and _SIGNED.search(title):
        return 0
    if _DRAFT.search(title):
        return 3
    if _RELEASE.search(title):
        return 2
    return 1


def _document_url(href: str, page_url: str) -> str:
    """The Matrix origin's URL for an asset, which is not behind Cloudflare.

    The council-domain URL in the page sits behind the council's Cloudflare
    zone, which challenges GitHub's runners; `lgasa-web.squiz.cloud/?a=<id>`
    serves the same file to a plain client. See `lgasa.DOCUMENT_ROOT`.
    """
    match = _ASSET.search(href)
    if match:
        return f"{DOCUMENT_ROOT}/?a={match[1]}"
    return urljoin(page_url, href)


@register_scraper
class AdelaidePlainsScraper(BaseScraper):
    # Cloudflare challenges GitHub's runners on every LGA SA council domain
    # and lets Chrome through only without the "HeadlessChrome" token; see
    # the lgasa module docstring.
    strip_headless_user_agent = True

    # One production year, measured 20 Oct 2026 from a home IP through
    # main.py: two Chrome page loads 20 s apart, 21 s. Orders dispatch only;
    # see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("adelaide_plains", "SA", _BASE_URL)
        self._last_request_at: Optional[float] = None

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _fetch(self, url: str) -> str:
        """One listing page through Chrome, retried once on a fresh browser.

        robots.txt (checked 20 Oct 2026, the Matrix default) sets
        `Crawl-delay: 20` and disallows only search, Funnelback query and
        Matrix-internal paths, none of which are requested. Both pages are
        on one host, so they are read 20 s apart, through `fetcher.sleep`
        so that replay does not wait.
        """
        last_error: Optional[Exception] = None
        for attempt in range(2):
            if self._last_request_at is not None:
                wait = CRAWL_DELAY_SECONDS - (time.monotonic() - self._last_request_at)
                if wait > 0:
                    self.fetcher.sleep(wait)
            self._last_request_at = time.monotonic()
            try:
                return self.fetcher.fetch_with_selenium(
                    url,
                    wait_time=CHALLENGE_WAIT_SECONDS,
                    wait_condition=EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "td.meetingInformation")
                    ),
                )
            except Exception as error:
                last_error = error
                self.logger.warning(
                    f"{self.council_name}: {url} failed (attempt {attempt + 1}/2): "
                    f"{type(error).__name__}: {error}"
                )
                self.fetcher.restart_driver()
        raise last_error

    @staticmethod
    def _rows(soup: BeautifulSoup, wanted: set[int]):
        """(date, [(category, title, href)]) per meeting row in a wanted year."""
        for table in soup.select("table[id]"):
            if not table["id"].isdigit() or int(table["id"]) not in wanted:
                continue
            for cell in table.select("td.meetingInformation"):
                stamp = cell.select_one(".meetingDate")
                date = _row_date(stamp.get_text(" ", strip=True)) if stamp else None
                if date is None:
                    continue
                documents = []
                for entry in cell.select("div.container"):
                    link = entry.select_one(".column-1 a[href]")
                    category = entry.select_one(".column-2")
                    if not link:
                        continue
                    documents.append(
                        (
                            (
                                category.get_text(" ", strip=True).lower()
                                if category
                                else ""
                            ),
                            re.sub(r"\s+", " ", link.get_text(" ", strip=True)),
                            link["href"],
                        )
                    )
                yield date, documents

    def _meetings(
        self, soup: BeautifulSoup, page_url: str, body: Optional[str], wanted: set[int]
    ) -> list[ScraperReturn]:
        # A row is one date, which can hold two meetings: on 26 June 2023 an
        # ordinary and a special meeting each have an agenda and minutes.
        # So papers are grouped by the meeting their title names as well as
        # the row's date.
        meetings: dict[tuple, dict[str, tuple[int, str]]] = {}
        # Papers whose title gives a date other than their row's.
        misfiled: list[tuple] = []
        for date, documents in self._rows(soup, wanted):
            for category, title, href in documents:
                if category in _SKIPPED_CATEGORIES:
                    continue
                stripped = _RELEASE_PREFIX.sub("", title)
                if _NOT_A_PAPER.search(stripped):
                    continue
                if _MINUTES.search(stripped):
                    kind = "minutes"
                elif _AGENDA.search(stripped):
                    kind = "agenda"
                elif category in ("agendas", "minutes"):
                    # "Signed - Special Council Meeting - 12 August 2020",
                    # filed under Minutes.
                    kind = "agenda" if category == "agendas" else "minutes"
                else:
                    continue
                key = (_meeting_name(stripped, body), date)
                paper = (_rank(kind, title), _document_url(href, page_url))
                title_dates = _title_dates(stripped)
                if title_dates and date not in title_dates:
                    misfiled.append((key, title_dates[-1], kind, paper))
                    continue
                papers = meetings.setdefault(key, {})
                if kind not in papers or paper[0] < papers[kind][0]:
                    papers[kind] = paper

        # The row date is the council's own field and usually right, but not
        # always. "Minutes - CAP - Council Assessment Panel - 19 March 2020"
        # sits in a row of its own dated 18 March, beside the 19 March row
        # holding that meeting's agenda; "Agenda - Special Council Meeting -
        # 04 March 2023" sits in the 4 March 2024 row with no 2023 meeting to
        # belong to. So a paper whose title disagrees with its row joins the
        # meeting its title names only where that meeting is listed and
        # lacks that paper, and otherwise stays with its row.
        for (name, date), title_date, kind, paper in misfiled:
            target = meetings.get((name, title_date))
            if target is not None and kind not in target:
                target[kind] = paper
                continue
            papers = meetings.setdefault((name, date), {})
            if kind not in papers or paper[0] < papers[kind][0]:
                papers[kind] = paper

        results = []
        for (name, date), papers in meetings.items():
            agenda = papers["agenda"][1] if "agenda" in papers else None
            minutes = papers["minutes"][1] if "minutes" in papers else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results = []
        for url, body in _LISTINGS:
            soup = BeautifulSoup(self._fetch(url), "html.parser")
            if not soup.select("td.meetingInformation"):
                # The wait condition passed, so this is a layout change.
                raise ValueError(f"{self.council_name}: no meeting rows on {url}")
            results.extend(self._meetings(soup, url, body, wanted))
        return results
