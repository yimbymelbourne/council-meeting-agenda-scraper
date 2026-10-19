"""Newcastle, Byron and Port Macquarie-Hastings read their pre-Resolve
meetings only for the years that need them.

Each council's older meetings are somewhere other than Resolve: Newcastle's
on its website's previous-council-terms pages, Byron's and Port
Macquarie-Hastings' on their old InfoCouncil sites. Production asks for the
current year, which none of those holds, so it must not fetch them; and a
history year must fetch only the pages that reach it. Cassette replay is
unfiltered and cannot see either, so these replay the same recordings with a
filter set.
"""

from __future__ import annotations

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.nsw.byron import ByronScraper
from aus_council_scrapers.scrapers.nsw.newcastle import (
    COMMITTEE_ARCHIVE,
    COUNCIL_ARCHIVE,
    NewcastleScraper,
)
from aus_council_scrapers.scrapers.nsw.port_macquarie_hastings import (
    PortMacquarieHastingsScraper,
)
from tests.cassette import PlaybackFetcher, cassette_paths


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


class _NoFetching(Fetcher):
    def fetch_with_requests(self, url, *args, **kwargs):
        raise AssertionError(f"fetched {url}")

    def fetch_with_selenium(self, url, *args, **kwargs):
        raise AssertionError(f"fetched {url}")

    def get_selenium_driver(self):
        raise AssertionError("opened a browser")


def _filtered_run(scraper, slug: str, year: int):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    recorded = next(v for k, v in replay if k == ["meta", "recorded_date"])

    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(recorded):
        results = [r.to_dict() for r in scraper.scraper()]
    return results, [r for r in expected if r["date"].startswith(str(year))], fetcher


def test_a_newcastle_history_year_reads_only_the_pages_that_reach_it():
    results, expected, fetcher = _filtered_run(NewcastleScraper(), "newcastle", 2023)

    assert results, "the filtered run found nothing to compare"
    assert results == expected
    # 2023 runs from the first page of each listing onto its second, where
    # it ends, so neither listing's third page is asked for. Resolve starts
    # in October 2024, so its API is not asked either.
    assert fetcher.urls == [
        COUNCIL_ARCHIVE,
        f"{COUNCIL_ARCHIVE}?page=2",
        COMMITTEE_ARCHIVE,
        f"{COMMITTEE_ARCHIVE}?page=2",
    ]


@pytest.mark.parametrize(
    "scraper_class, slug, infocouncil",
    [
        (ByronScraper, "byron", "https://byron.infocouncil.biz/"),
        (
            PortMacquarieHastingsScraper,
            "port_macquarie_hastings",
            "https://portmacquarie.infocouncil.biz/",
        ),
    ],
)
def test_an_infocouncil_history_year_is_one_request(scraper_class, slug, infocouncil):
    results, expected, fetcher = _filtered_run(scraper_class(), slug, 2024)

    assert results, "the filtered run found nothing to compare"
    assert results == expected
    assert fetcher.urls == [f"{infocouncil}?year=2024"]


@pytest.mark.parametrize(
    "scraper_class",
    [NewcastleScraper, ByronScraper, PortMacquarieHastingsScraper],
)
def test_the_production_year_never_touches_the_older_source(scraper_class):
    scraper = scraper_class()
    scraper.fetcher = _NoFetching()
    with clock.frozen("2026-10-20"):
        assert scraper.other_meetings({2026}) == []
