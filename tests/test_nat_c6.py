"""Douglas, Yorke Peninsula, Strathbogie, Adelaide Plains, Ararat and Mansfield.

Two contracts the cassette replay cannot see, because cassettes are recorded
unfiltered:

* `years_filter` decides what is fetched. Each of these scrapers chooses
  pages by year—Strathbogie's archive, Douglas's financial-year pages, Yorke
  Peninsula's year archives, Ararat's year pages, Mansfield's pager—so a
  filtered run must return exactly the fixture's meetings for that year
  while requesting fewer pages than the full recording.
* A refused fetch fails the council. None of them may turn a blocked runner
  into an empty list, which main.py would report as ok with 0 meetings.
* So does a page whose markup moved out from under the parse. Douglas and
  Mansfield each find meetings through one class name; renamed, the page
  still loads but nothing matches, and that too must fail rather than
  report 0 meetings.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BlockedByWAF, Fetcher
from aus_council_scrapers.scrapers.qld.douglas import DouglasShireScraper
from aus_council_scrapers.scrapers.sa.adelaide_plains import AdelaidePlainsScraper
from aus_council_scrapers.scrapers.sa.yorke_peninsula import YorkePeninsulaScraper
from aus_council_scrapers.scrapers.vic.ararat import AraratScraper
from aus_council_scrapers.scrapers.vic.mansfield import MansfieldScraper
from aus_council_scrapers.scrapers.vic.strathbogie import StrathbogieScraper
from tests.cassette import PlaybackFetcher, cassette_paths

# AGENTS.md's per-council aim for one production year.
_REQUEST_AIM = 20


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        self.requested.append(url)
        return super().fetch_with_selenium(url, wait_time, wait_condition)


def _sorted(results) -> list[dict]:
    return sorted(results, key=lambda r: (r["date"], r["name"], r["agenda_url"] or ""))


@pytest.mark.parametrize(
    "scraper_class, slug, year, fewer",
    [
        # The production year, for each council. Adelaide Plains holds every
        # year on its two pages, so it reads both whatever the year.
        (StrathbogieScraper, "strathbogie", 2026, True),
        (YorkePeninsulaScraper, "yorke_peninsula", 2026, True),
        (DouglasShireScraper, "douglas", 2026, True),
        (AraratScraper, "ararat", 2026, True),
        (MansfieldScraper, "mansfield", 2026, True),
        (AdelaidePlainsScraper, "adelaide_plains", 2026, False),
        # Years that live on a page of their own: Strathbogie's archive
        # (which needs both its pages), Douglas's 2019-20 and 2020-21 pages,
        # Yorke Peninsula's 2021 archives (whose panel papers carry no
        # year), Mansfield's third listing page.
        (StrathbogieScraper, "strathbogie", 2020, False),
        (DouglasShireScraper, "douglas", 2020, True),
        (YorkePeninsulaScraper, "yorke_peninsula", 2021, True),
        (MansfieldScraper, "mansfield", 2024, True),
    ],
)
def test_one_year_fetches_less_and_returns_that_years_meetings(
    scraper_class, slug, year, fewer
):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = [r for r in json.load(f) if parse_date(r["date"]).year == year]

    fetcher = _CountingPlayback(replay, slug)
    scraper = scraper_class()
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    assert expected, "the fixture has no meetings in this year to compare"
    assert _sorted(results) == _sorted(expected)

    recorded = [key for key, _ in replay if key[0] in ("requests", "selenium")]
    if fewer:
        assert len(fetcher.requested) < len(recorded)
    assert len(fetcher.requested) <= _REQUEST_AIM


class _RefusingFetcher(Fetcher):
    """Refuses every request the way a blocked runner sees it."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        raise BlockedByWAF(url, "test")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise TimeoutError(f"challenge never cleared on {url}")

    def get_selenium_driver(self):
        raise AssertionError("not driven directly")

    def sleep(self, seconds: float) -> None:
        # Adelaide Plains waits out its crawl delay before the retry.
        pass

    def restart_driver(self) -> None:
        pass

    def close(self):
        pass


@pytest.mark.parametrize(
    "scraper_class, error",
    [
        (StrathbogieScraper, BlockedByWAF),
        (YorkePeninsulaScraper, BlockedByWAF),
        (DouglasShireScraper, BlockedByWAF),
        (AraratScraper, BlockedByWAF),
        (MansfieldScraper, BlockedByWAF),
        (AdelaidePlainsScraper, TimeoutError),
    ],
)
def test_refused_fetch_fails_the_council(scraper_class, error):
    scraper = scraper_class()
    scraper.fetcher = _RefusingFetcher()
    scraper.years_filter = [2026]
    with pytest.raises(error):
        scraper.scraper()


@pytest.mark.parametrize(
    "scraper_class, slug, marker",
    [
        # The meeting toggles on Douglas's financial-year pages.
        (DouglasShireScraper, "douglas", "toggle-title"),
        # The Agenda and Minutes sections on Mansfield's meeting pages.
        (MansfieldScraper, "mansfield", "council-meeting__doc-item"),
    ],
)
def test_renamed_markup_fails_the_council(scraper_class, slug, marker):
    _, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = [
            [key, value.replace(marker, "renamed") if isinstance(value, str) else value]
            for key, value in json.load(f)
        ]
    fetcher = PlaybackFetcher(replay, slug)
    scraper = scraper_class()
    scraper.fetcher = fetcher
    scraper.years_filter = [2026]
    with clock.frozen(fetcher.recorded_date), pytest.raises(ValueError):
        scraper.scraper()
