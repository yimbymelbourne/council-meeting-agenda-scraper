"""Fetch failures and production cost for six regional councils.

Eurobodalla, Warrnambool, Bunbury, Harvey, South Gippsland and Central
Highlands (QLD).

The cassettes are recorded unfiltered and only ever replay success, so two
things they cannot show are checked here: a blocked or unreachable site fails
the council instead of reporting it with 0 meetings (AGENTS.md, "Never return
zero results"), and South Gippsland—the one of these whose cost grows with
the meetings it reads—fetches only the requested year's pages.
"""

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import BlockedByWAF, Fetcher
from aus_council_scrapers.scrapers.nsw.eurobodalla import EurobodallaScraper
from aus_council_scrapers.scrapers.qld.central_highlands_qld import (
    CentralHighlandsQldScraper,
)
from aus_council_scrapers.scrapers.vic.south_gippsland import SouthGippslandScraper
from aus_council_scrapers.scrapers.vic.warrnambool import WarrnamboolScraper
from aus_council_scrapers.scrapers.wa.bunbury import BunburyScraper
from aus_council_scrapers.scrapers.wa.harvey import HarveyScraper
from tests.cassette import PlaybackFetcher, cassette_paths


class _RefusingFetcher(Fetcher):
    """Serves from a recording where allowed, and refuses everything else."""

    def __init__(self, playback=None, allow=lambda url: False):
        self._playback = playback
        self._allow = allow
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        if self._playback is not None and self._allow(url):
            return self._playback.fetch_with_requests(url, method, **kwargs)
        raise BlockedByWAF(url, "test")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")


def _playback(slug: str) -> PlaybackFetcher:
    _, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        return PlaybackFetcher(json.load(f), slug)


@pytest.mark.parametrize(
    "scraper_class",
    [
        EurobodallaScraper,
        WarrnamboolScraper,
        BunburyScraper,
        HarveyScraper,
        SouthGippslandScraper,
        CentralHighlandsQldScraper,
    ],
)
def test_refused_everywhere_raises(scraper_class):
    scraper = scraper_class()
    scraper.fetcher = _RefusingFetcher()
    scraper.years_filter = [2026]
    with pytest.raises(BlockedByWAF):
        scraper.scraper()


def test_south_gippsland_raises_when_one_meeting_page_is_refused():
    # Everything loads except one meeting's page, and that page is the only
    # place its documents are linked: returning the rest would report the
    # year as whole with a meeting missing.
    result_path, _ = cassette_paths("south_gippsland")
    with open(result_path) as f:
        refused = next(
            m["webpage_url"] for m in json.load(f) if m["date"].startswith("2026")
        )
    scraper = SouthGippslandScraper()
    scraper.fetcher = _RefusingFetcher(
        _playback("south_gippsland"), allow=lambda url: url != refused
    )
    scraper.years_filter = [2026]
    with clock.frozen(scraper.fetcher._playback.recorded_date):
        with pytest.raises(BlockedByWAF):
            scraper.scraper()


def test_south_gippsland_fetches_only_the_requested_year():
    result_path, _ = cassette_paths("south_gippsland")
    with open(result_path) as f:
        expected = sorted(
            m["webpage_url"] for m in json.load(f) if m["date"].startswith("2025")
        )

    scraper = SouthGippslandScraper()
    scraper.fetcher = _RefusingFetcher(
        _playback("south_gippsland"), allow=lambda url: True
    )
    scraper.years_filter = [2025]
    with clock.frozen(scraper.fetcher._playback.recorded_date):
        got = scraper.scraper()

    assert sorted(m.webpage_url for m in got) == expected
    meeting_pages = [u for u in scraper.fetcher.requested if "/meetings/meeting/" in u]
    assert sorted(meeting_pages) == expected
    year_pages = [u for u in scraper.fetcher.requested if "/meetings/committee/" in u]
    assert len(year_pages) == 1 and year_pages[0].endswith("_2025")
