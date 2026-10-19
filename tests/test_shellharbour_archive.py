"""Shellharbour's pre-Resolve archive is read only for the years that need it.

The archive is a paged listing on www.shellharbour.nsw.gov.au, whose
robots.txt sets `Crawl-delay: 10`, so each page costs ten seconds of a
worker. Production asks for the current year, which the archive never holds.
Cassette replay is unfiltered and cannot see either cost, so these replay the
same recording with a filter set.
"""

from __future__ import annotations

import json

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.nsw.shellharbour import (
    ARCHIVE_URL,
    CRAWL_DELAY,
    ShellharbourScraper,
)
from tests.cassette import PlaybackFetcher, cassette_paths


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.calls: list[tuple[str, object]] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.calls.append(("fetch", url))
        return super().fetch_with_requests(url, method, **kwargs)

    def sleep(self, seconds):
        self.calls.append(("sleep", seconds))


class _NoFetching(Fetcher):
    def fetch_with_requests(self, url, *args, **kwargs):
        raise AssertionError(f"fetched {url}")

    def fetch_with_selenium(self, url, *args, **kwargs):
        raise AssertionError(f"fetched {url}")

    def get_selenium_driver(self):
        raise AssertionError("opened a browser")


def _load():
    result_path, replay_path = cassette_paths("shellharbour")
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    recorded = next(v for k, v in replay if k == ["meta", "recorded_date"])
    return replay, expected, recorded


def test_an_archive_year_reads_only_the_pages_it_needs_at_the_crawl_delay():
    replay, expected, recorded = _load()
    fetcher = _CountingPlayback(replay, "shellharbour")
    scraper = ShellharbourScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [2021]

    with clock.frozen(recorded):
        results = [r.to_dict() for r in scraper.scraper()]

    assert results, "the filtered run found nothing to compare"
    assert results == [r for r in expected if r["date"].startswith("2021")]
    # 2021 ends part-way down the second page, so the third is never asked
    # for, and the second waits out the site's Crawl-delay first. Resolve
    # starts in 2022, so its API is not asked either.
    assert fetcher.calls == [
        ("fetch", ARCHIVE_URL),
        ("sleep", CRAWL_DELAY),
        ("fetch", f"{ARCHIVE_URL}?page=1"),
    ]


def test_the_production_year_never_touches_the_archive():
    scraper = ShellharbourScraper()
    scraper.fetcher = _NoFetching()
    with clock.frozen("2026-10-20"):
        assert scraper.other_meetings({2026}) == []
