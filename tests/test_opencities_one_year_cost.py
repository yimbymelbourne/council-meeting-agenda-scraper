"""`years_filter` bounds what seven OpenCities councils fetch: Launceston,
Rockhampton, Western Downs, Isaac, Mackay, Warrumbungle and Edward River.

Cassettes are recorded unfiltered, so replay alone never sees what production
does: ask for one year. These tests replay each recording with
`years_filter` set and check both halves of that contract—the year's
meetings all come back, exactly as in the full run, and no listing page for
another year is requested. The second half is what keeps each council to
one listing request plus one payload per kept meeting.
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.edward_river import EdwardRiverScraper
from aus_council_scrapers.scrapers.nsw.warrumbungle import WarrumbungleScraper
from aus_council_scrapers.scrapers.qld.isaac import IsaacScraper
from aus_council_scrapers.scrapers.qld.mackay import MackayScraper
from aus_council_scrapers.scrapers.qld.rockhampton import RockhamptonScraper
from aus_council_scrapers.scrapers.qld.western_downs import WesternDownsScraper
from aus_council_scrapers.scrapers.tas.launceston import LauncestonScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_LISTING_YEAR = re.compile(r"\(dd_OC Year=(\d{4})\)")
_PAYLOAD = "documentrenderer"


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _sorted(results) -> list[dict]:
    return sorted(results, key=lambda r: (r["date"], r["name"], r["agenda_url"] or ""))


# Mackay's module holds only the current year, so that is the year to test.
_CASES = [
    (LauncestonScraper, 2025),
    (RockhamptonScraper, 2025),
    (WesternDownsScraper, 2025),
    (IsaacScraper, 2025),
    (MackayScraper, 2026),
    (WarrumbungleScraper, 2025),
    (EdwardRiverScraper, 2025),
]


@pytest.mark.parametrize(
    "scraper_class,year", _CASES, ids=[c.__name__ for c, _ in _CASES]
)
def test_one_year_fetches_only_that_year(scraper_class, year):
    scraper = scraper_class()
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)

    fetcher = _CountingPlayback(replay, scraper.council_name)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    wanted = _sorted(r for r in expected if parse_date(r["date"]).year == year)
    assert wanted, f"the cassette holds no {year} meetings to compare"
    assert _sorted(results) == wanted

    listings = [u for u in fetcher.requested if _PAYLOAD not in u]
    # One listing request: the year's own page, read with year_filtered_first_page
    # and page_size, never the bare listing or another year's.
    assert len(listings) == 1, listings
    assert {
        int(m.group(1)) for u in listings if (m := _LISTING_YEAR.search(unquote(u)))
    } == {year}
