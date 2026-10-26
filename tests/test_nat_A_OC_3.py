"""The eight regional Victorian OpenCities councils, run as production runs
them.

Production passes one year, and these scrapers then start from the listing
page already filtered to that year (`year_filtered_first_page`) rather than
the bare listing; Surf Coast alone pages the bare listing. The cassettes
are recorded unfiltered, so the scraper replay never takes that path. This replays each recording with one year set and
checks that the filtered run asks for nothing outside that year's listings
and payloads, and returns exactly the year's meetings from the full run.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

import aus_council_scrapers.scrapers  # noqa: F401  (fills the registry)
from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

_SLUGS = [
    "mildura",
    "surf_coast",
    "campaspe",
    "moira",
    "colac_otway",
    "swan_hill",
    "mount_alexander",
    "horsham",
]

# A complete past year in every recording.
_YEAR = 2025


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _key(record: dict) -> tuple:
    return (record["date"], record["name"], record["agenda_url"] or "")


@pytest.mark.parametrize("slug", _SLUGS)
def test_one_year_run_reads_only_that_years_listing(slug: str):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = sorted(
            (r for r in json.load(f) if parse_date(r["date"]).year == _YEAR),
            key=_key,
        )
    assert expected, f"{slug}: the recording has no {_YEAR} meetings to compare"

    scraper = next(s for s in SCRAPER_REGISTRY.values() if s.council_name == slug)
    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]
    try:
        with clock.frozen(fetcher.recorded_date):
            results = scraper.scraper()
    finally:
        del scraper.years_filter

    assert sorted((r.to_dict() for r in results), key=_key) == expected

    listings = [u for u in fetcher.requested if "documentrenderer" not in u]
    assert listings, f"{slug}: no listing page was requested"
    if scraper.main_listing().by_year:
        stray = [u for u in listings if f"(dd_OC%20Year={_YEAR})" not in u]
        assert not stray, f"{slug}: listing pages outside {_YEAR}: {stray}"
    else:
        # Surf Coast pages its unfiltered listing newest first (its year
        # filter drops meetings). Page 1 reaches back to 2023, so a 2025 run
        # stops there.
        assert len(listings) == 1, f"{slug}: {listings}"
        assert "dd_OC%20Year" not in listings[0], listings[0]
