"""Shire of Dumbleyung (WA).

The council's site is Wix. Each year's council meetings sit on a page of
their own (`/council-meetings-2025`, `/copy-of-council-meetings-2026`,
`/councilmeetings2019`), and the papers are not in that page at all: they
are in a "Table Master" widget (Wix app `134139f3-...`), an iframe served by
`wix-visual-data.appspot.com`. The iframe's HTML carries the whole table
inline, as a CSV string inside `var initialState = {...}`, so no browser is
needed. The chain is three plain requests:

1. `/_api/v1/access-tokens` on the council's site returns a signed
   `instance` token for every app on the site, Table Master included. It
   needs no cookie and is the same for every page.
2. Each year's page names the widget's component id
   (`<div id="comp-..."><iframe title="Table Master">`).
3. `wix-visual-data.appspot.com/index?instance=...&compId=...` returns the
   table. It answers 403 without a `Referer` from the council's site, so one
   is sent.

The year pages are found in `pages-sitemap.xml` (10 KB) rather than in the
1 MB navigation of a page, so a production year is the sitemap, the token,
that year's page and its table, and the electors' page and its table: six
requests. robots.txt on www.dumbleyung.wa.gov.au allows all of these paths
(it disallows only `*?lightbox=`); wix-visual-data.appspot.com and the
usrfiles.com document host answer robots.txt with 401 and 403, which
places no restriction (RFC 9309).

Each table row is one meeting: DATE, AGENDA, MINUTES (2019-2021 tables have
an empty column between the two). A paper cell is JSON, either
`{"type": "DocumentLink", "docId": "ugd/7929f4_....pdf"}`, served at
`/_files/ugd/...` on the council's domain, or (older tables)
`{"type": "webAddress", "href": "https://<site>.usrfiles.com/ugd/...pdf"}`.
Rows with no date hold a late agenda item or an attachment for the meeting
above (`16.1 - PUBLIC COPY - Late Agenda Item.pdf`); they are not that
meeting's agenda, so they are skipped.

Committee meetings (bushfire advisory, LEMC, audit and risk) are on
`/committeemeetings` and are left out, as for other WA councils; council
meetings (ordinary and special) and electors' meetings are read.
"""

import csv
import io
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_ORIGIN = "https://www.dumbleyung.wa.gov.au"
_SITEMAP_URL = f"{_ORIGIN}/pages-sitemap.xml"
_TOKENS_URL = f"{_ORIGIN}/_api/v1/access-tokens"
_ELECTORS_URL = f"{_ORIGIN}/electorsmeetings"
_TABLE_MASTER_APP = "134139f3-f2a0-2c2c-693c-ed22165cfd84"
_WIDGET_URL = "https://wix-visual-data.appspot.com/index"
_WIDGET_HEADERS = {"Referer": f"{_ORIGIN}/"}

# "council-meetings-2025", "councilmeetings2019", and the 2026 page, which
# was made by copying 2025's and keeps the "copy-of-" prefix.
_YEAR_PAGE = re.compile(r"council-?meetings-?(20\d{2})$")
_LOC = re.compile(r"<loc>([^<]+)</loc>")
_INITIAL_STATE = re.compile(r"var initialState\s*=\s*")

# "12 Feb 2026", "8 February 2024", and one "16 Ap 2025" (the April 2025
# agenda's cover says 16 April 2025), so a month is any unambiguous prefix.
_DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(20\d{2})$")
_MONTHS = [
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
]

_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


def _parse_date(text: str) -> Optional[str]:
    match = _DATE.match(re.sub(r"\s+", " ", text).strip())
    if not match:
        return None
    day, month_text, year = match.groups()
    candidates = [
        number
        for number, month in enumerate(_MONTHS, start=1)
        if len(month_text) >= 2 and month.startswith(month_text.lower())
    ]
    if len(candidates) != 1:
        return None
    return f"{year}-{candidates[0]:02d}-{int(day):02d}"


@register_scraper
class DumbleyungScraper(BaseScraper):
    # One production year (--years 2026) took 7.6 s from a home IP on 26 Oct
    # 2026: six requests over two hosts. Orders dispatch only; see
    # BaseScraper.expected_seconds.
    expected_seconds = 8

    def __init__(self):
        super().__init__("dumbleyung", "WA", _ORIGIN)
        self._logger = logging.getLogger(self.__class__.__name__)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        pages = self._year_pages(wanted)
        instance = self._widget_instance()

        meetings: list[ScraperReturn] = []
        for url in pages:
            meetings += self._read_page(url, instance, wanted, electors=False)
        meetings += self._read_page(_ELECTORS_URL, instance, wanted, electors=True)

        if not meetings:
            raise ValueError(
                f"dumbleyung: no meetings with papers for {sorted(wanted)}"
            )
        meetings.sort(key=lambda m: (m.date, m.name))
        return meetings

    def _year_pages(self, wanted: set[int]) -> list[str]:
        sitemap = self.fetcher.fetch_with_requests(_SITEMAP_URL)
        by_year: dict[int, list[str]] = {}
        for url in _LOC.findall(sitemap):
            url = url.strip()
            match = _YEAR_PAGE.search(urlparse(url).path)
            if match:
                by_year.setdefault(int(match.group(1)), []).append(url)
        if not by_year:
            raise ValueError("dumbleyung: no council-meetings pages in the sitemap")

        today = clock.today()
        pages = []
        for year in sorted(wanted):
            if year in by_year:
                pages += by_year[year]
            elif year > today.year:
                continue
            elif year == today.year and today.month <= 3:
                # The new year's page is made by hand, some weeks into the
                # year (the first meeting is in February).
                self._logger.warning(
                    f"dumbleyung: no {year} council-meetings page in the sitemap yet"
                )
            else:
                raise ValueError(
                    f"dumbleyung: no {year} council-meetings page in the sitemap; "
                    f"found {sorted(by_year)}"
                )
        return pages

    def _widget_instance(self) -> str:
        tokens = json.loads(self.fetcher.fetch_with_requests(_TOKENS_URL))
        try:
            return tokens["apps"][_TABLE_MASTER_APP]["instance"]
        except (KeyError, TypeError):
            raise ValueError(
                "dumbleyung: access-tokens returned no Table Master instance"
            )

    def _read_page(
        self, url: str, instance: str, wanted: set[int], electors: bool
    ) -> list[ScraperReturn]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        components = [
            frame.parent.get("id")
            for frame in soup.select('iframe[title="Table Master"]')
            if frame.parent is not None and frame.parent.get("id")
        ]
        if not components:
            raise ValueError(f"dumbleyung: no Table Master widget on {url}")

        meetings = []
        for component in components:
            rows = self._table(instance, component)
            meetings += self._meetings(rows, url, wanted, electors)
        return meetings

    def _table(self, instance: str, component: str) -> list[list[str]]:
        html = self.fetcher.fetch_with_requests(
            _WIDGET_URL,
            params={"instance": instance, "compId": component, "viewMode": "site"},
            headers=_WIDGET_HEADERS,
        )
        match = _INITIAL_STATE.search(html)
        if not match:
            raise ValueError(f"dumbleyung: no table data in widget {component}")
        state, _ = json.JSONDecoder().raw_decode(html, match.end())
        data = state["data"]["settings"]["data"]
        if data.get("type") != "csvString":
            raise ValueError(
                f"dumbleyung: widget {component} reads {data.get('type')!r}, "
                f"not an inline table"
            )
        return list(csv.reader(io.StringIO(data["csvString"])))

    def _meetings(
        self, rows: list[list[str]], page_url: str, wanted: set[int], electors: bool
    ) -> list[ScraperReturn]:
        header = [cell.strip().upper() for cell in rows[0]] if rows else []
        try:
            date_col = header.index("DATE")
            agenda_col = next(i for i, h in enumerate(header) if h.startswith("AGENDA"))
            minutes_col = next(i for i, h in enumerate(header) if h.startswith("MINUTES"))
        except (ValueError, StopIteration):
            raise ValueError(f"dumbleyung: unexpected table header {header} on {page_url}")

        meetings = []
        for row in rows[1:]:
            cell = lambda i: row[i] if i < len(row) else ""
            date_text = cell(date_col).strip()
            if not date_text:
                # A late item or attachment for the meeting above.
                continue
            agenda = self._paper(cell(agenda_col), _AGENDA, page_url)
            minutes = self._paper(cell(minutes_col), _MINUTES, page_url)
            date = _parse_date(date_text)
            if date is None:
                if agenda or minutes:
                    self._logger.warning(
                        f"dumbleyung: undated row {date_text!r} on {page_url} left out"
                    )
                continue
            if int(date[:4]) not in wanted or not (agenda or minutes):
                continue

            labels = " ".join(p[0] for p in (agenda, minutes) if p)
            special = bool(_SPECIAL.search(labels))
            if electors:
                name = "Special Meeting of Electors" if special else "Annual Meeting of Electors"
            else:
                name = "Special Council Meeting" if special else "Ordinary Council Meeting"

            agenda_url = agenda[1] if agenda else None
            minutes_url = minutes[1] if minutes else None
            meetings.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return meetings

    def _paper(
        self, cell: str, kind: re.Pattern, page_url: str
    ) -> Optional[tuple[str, str]]:
        """(label, url) for a PDF of the column's kind, else None."""
        cell = cell.strip()
        if not cell.startswith("{"):
            return None
        paper = json.loads(cell)
        label = re.sub(r"\s+", " ", paper.get("text") or "").strip()
        if paper.get("href"):
            url = paper["href"]
        elif paper.get("docId"):
            url = f"{_ORIGIN}/_files/{paper['docId']}"
        else:
            return None
        if not urlparse(url).path.lower().endswith(".pdf"):
            self._logger.warning(f"dumbleyung: {label!r} is not a PDF ({url}); skipped")
            return None
        if not kind.search(label):
            self._logger.warning(
                f"dumbleyung: {label!r} filed in the wrong column on {page_url}; skipped"
            )
            return None
        return label, url
