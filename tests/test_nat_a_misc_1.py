"""What the A-MISC-1 scrapers fetch and refuse to return, beyond their replays.

The cassette replays (tests/scraper_test.py) pin every meeting these scrapers
emit, but they are recorded unfiltered and with every request answering. Two
contracts sit outside that:

- **Production cost.** Production passes one year. Augusta Margaret River and
  West Tamar each fetch a page per year, so a scraper that ignored
  `years_filter` would return the same meetings and spend several extra
  requests a night doing it. The replay cannot see that.
- **No silent empty result.** A listing that comes back empty for a year
  that is well under way means the markup changed or the page was blocked,
  and council-alerts records a returned `[]` as a successful scrape. That
  holds for Augusta Margaret River's page-type fragment and for the Ionata
  archives of West Tamar and Glamorgan Spring Bay.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.tas.glamorgan_spring_bay import (
    GlamorganSpringBayScraper,
)
from aus_council_scrapers.scrapers.tas.west_tamar import WestTamarScraper
from aus_council_scrapers.scrapers.wa.augusta_margaret_river import (
    AugustaMargaretRiverScraper,
)
from tests.cassette import PlaybackFetcher, cassette_paths

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


def _key(meeting: dict) -> tuple:
    return (meeting["date"], meeting["name"], meeting["agenda_url"] or "")


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[tuple[str, str]] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append((method, url))
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize(
    "slug, scraper_class, expected_requests",
    [
        # The listing page for its hidden filter inputs, then one POST.
        ("augusta_margaret_river", AugustaMargaretRiverScraper, 2),
        # One ?f_year= page; a year of West Tamar fits on it.
        ("west_tamar", WestTamarScraper, 1),
    ],
)
def test_one_year_costs_only_that_years_requests(
    slug, scraper_class, expected_requests
):
    replay, expected = _load(slug)
    scraper = scraper_class()
    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]

    with clock.frozen(_recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    wanted = sorted(
        (m for m in expected if parse_date(m["date"]).year == _YEAR), key=_key
    )
    assert wanted, f"the {slug} fixture has no {_YEAR} meetings to compare"
    assert sorted(results, key=_key) == wanted
    assert len(fetcher.requested) == expected_requests, fetcher.requested


class _EmptyFragments(PlaybackFetcher):
    """The recorded listing page, but every search answers with nothing."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if method == "POST":
            return json.dumps({"htmlResult": ""})
        return super().fetch_with_requests(url, method, **kwargs)


def test_augusta_margaret_river_raises_when_a_past_year_lists_nothing():
    replay, _ = _load("augusta_margaret_river")
    scraper = AugustaMargaretRiverScraper()
    scraper.fetcher = _EmptyFragments(replay, "augusta_margaret_river")
    scraper.years_filter = [_YEAR]

    with clock.frozen(_recorded_date(replay)):
        with pytest.raises(RuntimeError, match="no Council meetings"):
            scraper.scraper()


class _NoCards(PlaybackFetcher):
    """Every listing page answers with a page that has no meeting cards."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return "<html><body><main><p>Nothing found.</p></main></body></html>"


@pytest.mark.parametrize(
    "slug, scraper_class, year",
    [
        ("west_tamar", WestTamarScraper, 2026),
        ("glamorgan_spring_bay", GlamorganSpringBayScraper, 2026),
    ],
)
def test_ionata_councils_raise_when_a_covered_year_lists_nothing(
    slug, scraper_class, year
):
    replay, _ = _load(slug)
    scraper = scraper_class()
    scraper.fetcher = _NoCards(replay, slug)
    scraper.years_filter = [year]

    with clock.frozen(_recorded_date(replay)):
        with pytest.raises(RuntimeError, match="no meetings with documents"):
            scraper.scraper()


def test_ionata_councils_allow_an_empty_year_before_their_archive_starts():
    # Glamorgan Spring Bay's rebuilt site holds 2026 only, so an empty 2025
    # is the council's history, not a broken page.
    replay, _ = _load("glamorgan_spring_bay")
    scraper = GlamorganSpringBayScraper()
    scraper.fetcher = _NoCards(replay, "glamorgan_spring_bay")
    scraper.years_filter = [2025]

    with clock.frozen(_recorded_date(replay)):
        assert scraper.scraper() == []
