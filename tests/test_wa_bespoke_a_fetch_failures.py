"""
A blocked or unreachable site must fail the council, not report it empty.

These scrapers skip a page that fails so one bad page does not cost the
rest. The risk in that is the case AGENTS.md describes for `bayside_nsw`: a
runner that is blocked outright gets [] back, and main.py reports the
council as ok with 0 meetings. So when nothing comes back and a fetch
failed, the scraper has to raise.
"""

import json

import pytest

from aus_council_scrapers.base import BlockedByWAF, Fetcher
from aus_council_scrapers.scrapers.wa.belmont import BelmontScraper
from aus_council_scrapers.scrapers.wa.kalamunda import KalamundaScraper
from aus_council_scrapers.scrapers.wa.perth import PerthScraper
from aus_council_scrapers.scrapers.wa.south_perth import SouthPerthScraper
from tests.cassette import PlaybackFetcher, cassette_paths


class _RefusingFetcher(Fetcher):
    """Serves the given pages, and refuses every other URL with a 403."""

    def __init__(self, pages: dict[str, str] | None = None):
        self._pages = pages or {}

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url in self._pages:
            return self._pages[url]
        raise BlockedByWAF(url, "test")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")

    def close(self):
        pass


@pytest.mark.parametrize(
    "scraper_class", [KalamundaScraper, SouthPerthScraper, BelmontScraper]
)
def test_refused_everywhere_raises(scraper_class):
    scraper = scraper_class()
    scraper.fetcher = _RefusingFetcher()
    scraper.years_filter = [2026]
    with pytest.raises(BlockedByWAF):
        scraper.scraper()


def test_perth_raises_when_every_meeting_page_is_refused():
    # Perth's landing page loads but its current-year documents are only on
    # per-meeting pages, so this is the shape a partial block would take.
    _, replay_path = cassette_paths("perth")
    with open(replay_path) as f:
        playback = PlaybackFetcher(json.load(f), "perth")
    landing_url = "https://perth.wa.gov.au/council/council-meetings"
    landing = playback.fetch_with_requests(landing_url)

    scraper = PerthScraper()
    scraper.fetcher = _RefusingFetcher({landing_url: landing})
    scraper.years_filter = [2026]
    with pytest.raises(BlockedByWAF):
        scraper.scraper()
