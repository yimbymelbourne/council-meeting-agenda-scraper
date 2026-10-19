"""`years_filter` bounds what North Sydney and Banyule fetch, not just what
they return.

Production passes one year, and `main.py` filters the results afterwards, so
a scraper that ignores the filter returns exactly the same meetings — it just
spends minutes of the shared nightly budget fetching pages that get thrown
away. Nothing in the cassette replay notices, because cassettes are recorded
unfiltered. These tests replay the same recordings with a filter set and
check both halves: the year's meetings all still come back, and the pages for
other years are never requested.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.north_sydney import NorthSydneyScraper
from aus_council_scrapers.scrapers.vic.banyule import (
    BanyuleScraper,
    _parse_listing_items,
)
from tests.cassette import PlaybackFetcher, cassette_paths

# A complete past year in both recordings, so the filtered run has pages to
# skip on both sides of it.
_YEAR = 2025


def _load(slug: str) -> tuple[list, list[dict]]:
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    return replay, expected


def _recorded_date(replay: list) -> str:
    return next(value for key, value in replay if key == ["meta", "recorded_date"])


def _sorted(results) -> list[dict]:
    # Order is not the contract here; which meetings come back is.
    return sorted(results, key=lambda r: (r["date"], r["name"], r["agenda_url"] or ""))


def _meetings_in(results: list[dict], year: int) -> list[dict]:
    return _sorted(r for r in results if parse_date(r["date"]).year == year)


class _CountingPlayback(PlaybackFetcher):
    """Playback that remembers which URLs the scraper asked for."""

    def __init__(self, replay_data, slug, driver=None):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []
        self._driver = driver

    def get_selenium_driver(self):
        return self._driver if self._driver else super().get_selenium_driver()

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        self.requested.append(url)
        return super().fetch_with_selenium(url, wait_time, wait_condition)


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
    that drives the page differently — which is the point of the filter —
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
