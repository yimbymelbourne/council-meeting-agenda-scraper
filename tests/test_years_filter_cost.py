"""`years_filter` bounds what North Sydney, Banyule and Port Phillip fetch, not
just what they return.

Production passes one year, and `main.py` filters the results afterwards, so
a scraper that ignores the filter returns exactly the same meetings—it just
spends minutes of the shared nightly budget fetching pages that get thrown
away. Nothing in the cassette replay notices, because cassettes are recorded
unfiltered. These tests replay the same recordings with a filter set and
check both halves: the year's meetings all still come back, and the pages for
other years are never requested.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.north_sydney import NorthSydneyScraper
from aus_council_scrapers.scrapers.vic.port_phillip import PortPhilipScraper
from aus_council_scrapers.scrapers.vic.banyule import (
    BanyuleScraper,
    _parse_listing_items,
)
from tests.replay_cost import (
    CountingPlayback as _CountingPlayback,
    load_cassette as _load,
    meetings_in as _meetings_in,
    recorded_date as _recorded_date,
    sorted_meetings as _sorted,
)

# A complete past year in both recordings, so the filtered run has pages to
# skip on both sides of it.
_YEAR = 2025


# --------------------------------------------------------------------------
# North Sydney: a listing page per ten meetings, then a page per meeting
# --------------------------------------------------------------------------

# Meeting pages carry their date in the slug: /council-meetings/304/24-08-2026-…
_MEETING_PAGE = re.compile(r"/council-meetings/\d+/\d{2}-\d{2}-(\d{4})-")
_LISTING_PAGE = re.compile(r"/council-meetings(?:\?page=(\d+))?$")


def test_north_sydney_fetches_only_the_wanted_years_pages():
    replay, expected = _load("north_sydney")
    fetcher = _CountingPlayback(replay, "north_sydney")
    scraper = NorthSydneyScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]

    with clock.frozen(_recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    assert results, "the filtered run found nothing to compare"
    assert _sorted(results) == _meetings_in(expected, _YEAR)

    meeting_years = {
        int(m.group(1)) for url in fetcher.requested if (m := _MEETING_PAGE.search(url))
    }
    assert meeting_years == {_YEAR}

    def listing_pages(urls):
        return {
            int(m.group(1) or 1)
            for url in urls
            if (m := _LISTING_PAGE.search(url))
        }

    recorded_pages = listing_pages(key[1] for key, _ in replay if key[0] == "requests")
    # Paging stops once the listing is past the year, rather than walking the
    # archive to its end.
    assert max(listing_pages(fetcher.requested)) < max(recorded_pages)


# --------------------------------------------------------------------------
# Banyule: Selenium postbacks, then a browser page load per meeting
# --------------------------------------------------------------------------

_NEXT_CLICK = "ctl11$ctl00$ctl16"
_YEAR_VALUE = re.compile(r"\.value = '(\d*)'")


class _ListingDriver:
    """Stands in for Banyule's listing page, built from the recorded one.

    The cassette's driver calls replay strictly in recorded order, so a run
    that drives the page differently—which is the point of the filter—
    cannot replay them. The recorded page sources are still the real pages,
    though: grouped by the year filter that produced them, they are enough
    to answer "next page" and "apply year" the way the site did.
    """

    def __init__(self, replay: list):
        ops = sorted(
            (key[1], key[2], key[3], value) for key, value in replay if key[0] == "driver"
        )
        self.pages: dict[str, list[str]] = {"": []}
        current = ""
        for _, op, args, value in ops:
            if op == "page_source":
                self.pages[current].append(value)
            elif op == "execute_script" and (m := _YEAR_VALUE.search(args)):
                current = m.group(1)
                self.pages[current] = []

        self.years_applied: list[str] = []
        self.unfiltered_pages_read = 0
        self._filter = ""
        self._page = 0

    @property
    def page_source(self) -> str:
        if self._filter == "":
            self.unfiltered_pages_read = max(self.unfiltered_pages_read, self._page + 1)
        return self.pages[self._filter][self._page]

    def execute_script(self, script: str, *args):
        if m := _YEAR_VALUE.search(script):
            self._filter, self._page = m.group(1), 0
            self.years_applied.append(self._filter)
        elif _NEXT_CLICK in script:
            self._page += 1


def test_banyule_posts_back_and_fetches_only_the_wanted_year():
    replay, expected = _load("banyule")
    driver = _ListingDriver(replay)
    fetcher = _CountingPlayback(replay, "banyule", driver=driver)
    scraper = BanyuleScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]

    with clock.frozen(_recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    assert results, "the filtered run found nothing to compare"
    assert _sorted(results) == _meetings_in(expected, _YEAR)

    assert driver.years_applied == [str(_YEAR)]
    assert driver.unfiltered_pages_read < len(driver.pages[""])

    listed_year = {
        cvid: parse_date(date).year
        for sources in driver.pages.values()
        for source in sources
        for date, _, cvid in _parse_listing_items(BeautifulSoup(source, "html.parser"))
    }
    fetched_years = {
        listed_year[url.rsplit("cvid=", 1)[1]]
        for url in fetcher.requested
        if "OCServiceHandler" in url
    }
    assert fetched_years == {_YEAR}


# --------------------------------------------------------------------------
# Port Phillip: InfoCouncil, plus an archive page that holds 2022 and 2023
# --------------------------------------------------------------------------


def test_port_phillip_skips_its_archive_for_a_year_infocouncil_carries():
    """The archive page answered 429 in a full nightly run, and in a one-year
    run it could add nothing anyway."""
    replay, expected = _load("port_phillip")
    fetcher = _CountingPlayback(replay, "port_phillip")
    scraper = PortPhilipScraper()
    scraper.fetcher = fetcher
    year = int(_recorded_date(replay)[:4])
    scraper.years_filter = [year]

    with clock.frozen(_recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    assert _meetings_in(results, year) == _meetings_in(expected, year)
    assert _meetings_in(expected, year), "the recording has no meetings that year"
    assert not [url for url in fetcher.requested if "portphillip.vic.gov.au" in url]
