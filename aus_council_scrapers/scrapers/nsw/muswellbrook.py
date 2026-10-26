"""Muswellbrook Shire Council (Upper Hunter).

A custom WordPress theme. The ``/meetings/`` index links one page per year,
and the slugs are not uniform—``/meetings/2026-council-meetings/`` and
``/meetings/2026-committee-meetings/`` for 2025 onwards, plain
``/meetings/2024/`` back to 2017—so the index is read rather than the URLs
built. Nothing earlier than 2017 is online; the site asks for an email.

Each year page is one static list: an ``li.dated-accordion__list-item`` per
meeting, with the meeting type in ``h3.dated-accordion__subtitle``, an ISO
datetime in ``time.dated-accordion__time[datetime]``, and the papers as
``a.file-list__link``, labelled "Business Paper (13 MB)", "Business Paper -
Part 1 (27 MB)", "Minutes (261 KB)" and, in 2020, "Agenda". Beside them sit
livestream links, item attachments, supplementary papers and draft plans on
exhibition, none of which is the agenda.

Papers are paired by the accordion item, never by filename: filenames are
typed by hand and sometimes wrong. The 23 June 2026 meeting's minutes are
``20260323-Ordinary-Council-Meeting-Minutes.pdf``, and that file is the June
minutes (its first page reads "held ... on Tuesday 23 June 2026"), not March's.

Committee meetings (Planning and Environment, State Significant Development,
Finance and Governance and the rest) are on their own page from 2025 and are
kept: the page is one request whatever it lists, and two of the committees are
the council's planning bodies.

robots.txt sets ``Crawl-delay: 10`` for every agent we could be, so requests
are spaced 10 s apart. A production year is the index and that year's one or
two pages: three requests, about 20 s.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.muswellbrook.nsw.gov.au"
_INDEX_URL = f"{_BASE_URL}/meetings/"

# robots.txt: "User-agent: * / Crawl-delay: 10".
_CRAWL_DELAY = 10

# /meetings/2026-council-meetings/, /meetings/2025-committee-meetings/,
# /meetings/2024/.
_YEAR_PAGE = re.compile(r"/meetings/(20\d\d)(?:-[a-z-]+)?/?$")

# "Business Paper", "Business Paper - Part 1", "Business Paper Pt 1", the
# 2023 typo "Business Part - Part 1", and 2020's "Agenda" / "Agenda -
# 18/02/2025". Matched at the start, so "Supplementary Business Paper" and
# "Late Item - Business Paper" are not the agenda.
_AGENDA = re.compile(r"^(?:business\s+pa(?:per|rt)|agenda)\b", re.IGNORECASE)
_MINUTES = re.compile(r"^minutes\b", re.IGNORECASE)
# "Business Paper Attachments Part 1" is the attachment book.
_NOT_THE_PAPER = re.compile(r"\battachments?\b|\bsupplementary\b|\blate\b", re.IGNORECASE)
# A business paper split into parts: Part 1 carries the agenda and the reports
# that open it, the later parts continue them.
_PART = re.compile(r"\b(?:part|pt)\.?\s*(\d+)\b", re.IGNORECASE)
# The size the theme appends to every label, "(13 MB)".
_SIZE = re.compile(r"\s*\(\s*[\d.,]+\s*[KMG]?B\s*\)\s*$", re.IGNORECASE)

# Upper Hunter County Council, the regional weeds authority, is a council of
# its own; its 2020 papers were filed on this page.
_NOT_THIS_COUNCIL = re.compile(r"\bcounty council\b", re.IGNORECASE)


def _label(link: Tag) -> str:
    return _SIZE.sub("", " ".join(link.get_text(" ", strip=True).split()))


@register_scraper
class MuswellbrookScraper(BaseScraper):
    # The index and 2026's two pages, 10 s apart: 20.7 s for `--years 2026`
    # from a home connection, 20 October 2026.
    expected_seconds = 21.0

    def __init__(self):
        super().__init__("muswellbrook", "NSW", _BASE_URL)
        self._fetched_once = False

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _fetch(self, url: str) -> str:
        if self._fetched_once:
            # The fetcher's own spacing is FETCH_DELAY (2 s); the crawl delay
            # is on top of it. Through the fetcher so replay does not wait.
            self.fetcher.sleep(_CRAWL_DELAY)
        self._fetched_once = True
        return self.fetcher.fetch_with_requests(url)

    def _year_pages(self) -> dict[int, list[str]]:
        soup = BeautifulSoup(self._fetch(_INDEX_URL), "html.parser")
        pages: dict[int, list[str]] = {}
        for link in soup.find_all("a", href=True):
            url = urljoin(_INDEX_URL, link["href"])
            match = _YEAR_PAGE.search(urlparse(url).path)
            if match and url not in pages.get(int(match.group(1)), []):
                pages.setdefault(int(match.group(1)), []).append(url)
        if not pages:
            raise RuntimeError(f"muswellbrook: no year pages linked from {_INDEX_URL}")
        return pages

    @staticmethod
    def _papers(item: Tag) -> tuple[Optional[str], Optional[str]]:
        agendas: list[tuple[int, str]] = []
        minutes_url = None
        for link in item.select("a[href]"):
            url = urljoin(_BASE_URL, link["href"].strip())
            if not urlparse(url).path.lower().endswith(".pdf"):
                continue
            label = _label(link)
            if _NOT_THE_PAPER.search(label):
                continue
            if _MINUTES.match(label):
                minutes_url = minutes_url or url
            elif _AGENDA.match(label):
                part = _PART.search(label)
                agendas.append((int(part.group(1)) if part else 0, url))
        # The whole paper (no part number) first, else Part 1.
        agenda_url = min(agendas)[1] if agendas else None
        return agenda_url, minutes_url

    @staticmethod
    def _tidy_name(name: str) -> str:
        """One spelling per committee.

        Each entry is typed afresh, so one committee appears as "Finance and
        Governance Committee", "Finance & Governance Committee" and "Finance
        & Governance Committee Meeting". The ampersand and a trailing
        "Meeting" after "Committee" are the only differences, so those are
        evened out; "Advisory" stays, since it is part of a name the council
        used.
        """
        name = " ".join(name.replace("&", " and ").split())
        return re.sub(r"(\bcommittee) meeting$", r"\1", name, flags=re.IGNORECASE)

    @staticmethod
    def _plausible_time(clock_time: str) -> Optional[str]:
        """The start time, or None where the theme has none to give.

        Midnight is the theme's blank. One entry is also plainly a typo: the
        29 June 2021 ordinary meeting is stamped 06:00, beside 18:00 for every
        other ordinary meeting that year. No meeting here starts before
        11 am, so a time before 7 am is treated as missing, not guessed at.
        """
        if clock_time == "00:00" or clock_time < "07:00":
            return None
        return clock_time

    def _read_page(self, url: str, wanted: set[int]) -> list[ScraperReturn]:
        soup = BeautifulSoup(self._fetch(url), "html.parser")
        items = soup.select("li.dated-accordion__list-item")
        if not items:
            raise RuntimeError(f"muswellbrook: no meetings listed on {url}")
        results = []
        for item in items:
            time_el = item.select_one("time[datetime]")
            subtitle = item.select_one(".dated-accordion__subtitle")
            if time_el is None or subtitle is None:
                self.logger.warning(f"muswellbrook: a meeting on {url} has no date or type")
                continue
            # "2026-06-23T17:00:00+10:00": the offset is the meeting's own, so
            # the first ten characters are its local date.
            stamp = time_el["datetime"]
            date, clock_time = stamp[:10], stamp[11:16]
            if int(date[:4]) not in wanted:
                continue
            agenda_url, minutes_url = self._papers(item)
            if not agenda_url and not minutes_url:
                continue
            # "Extra-Ordinary Council Meeting – 22 March, 2023": the date is
            # already in the record.
            name = re.split(r"\s+[–—-]\s+\d", subtitle.get_text(" ", strip=True))[0]
            if _NOT_THIS_COUNCIL.search(name):
                continue
            results.append(
                ScraperReturn(
                    name=self._tidy_name(name),
                    date=date,
                    time=self._plausible_time(clock_time),
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return self._drop_copied_entries(results)

    def _drop_copied_entries(self, results: list[ScraperReturn]) -> list[ScraperReturn]:
        """Drop an Extra-Ordinary entry that is a copy of the ordinary one.

        The 2020 page lists 25 February and 28 April twice, once as the
        Ordinary Council Meeting and once as an Extra-Ordinary one, and both
        entries link the same papers—``20200225-Ordinary-Council-Meeting-
        Business-Paper.pdf`` on both, and on 28 April that file and its
        re-upload with a ``-1`` suffix. A real extra-ordinary meeting has
        papers of its own, named for it ("Extra-Ordinary-Council-Meeting-
        Business-Paper"), so an extra-ordinary entry whose papers are all an
        ordinary meeting's, on a night that has an ordinary meeting, is folded
        into that meeting. Folded, not dropped: on 25 February the copy holds
        the minutes (``Ordinary-Council-Meeting-Minutes-25-February-2020.pdf``)
        and the ordinary entry does not.
        """
        ordinary = {
            r.date: r for r in results if r.name.lower().startswith("ordinary council")
        }

        def ordinary_papers_only(record: ScraperReturn) -> bool:
            names = [
                urlparse(u).path.rsplit("/", 1)[-1].lower()
                for u in (record.agenda_url, record.minutes_url)
                if u
            ]
            return all("ordinary" in n and "extra" not in n for n in names)

        kept = []
        for record in results:
            target = ordinary.get(record.date)
            if (
                target is not None
                and record.name.lower().startswith("extra-ordinary council")
                and ordinary_papers_only(record)
            ):
                self.logger.warning(
                    f"muswellbrook: the {record.date} Extra-Ordinary entry links only "
                    f"the Ordinary meeting's papers; folded into it as a copy"
                )
                target.agenda_url = target.agenda_url or record.agenda_url
                target.minutes_url = target.minutes_url or record.minutes_url
                target.download_url = target.agenda_url or target.minutes_url
                continue
            kept.append(record)
        return kept

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        self._fetched_once = False
        wanted = self._wanted_years()
        pages = self._year_pages()
        missing = sorted(y for y in wanted if y <= clock.current_year() and y not in pages)
        if missing:
            self.logger.warning(f"muswellbrook: no year page linked for {missing}")
        results: list[ScraperReturn] = []
        for year in sorted(pages, reverse=True):
            if year not in wanted or year < EARLIEST_YEAR:
                continue
            for url in pages[year]:
                results.extend(self._read_page(url, wanted))
        if not results:
            self.logger.warning(f"muswellbrook: no meetings with papers for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
