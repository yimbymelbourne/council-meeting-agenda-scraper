"""
The seven D-6 scrapers fail loudly on a changed page, but not in January.

`run_scraper` reports a returned [] as an ok council with 0 meetings, so a
listing that parses to nothing has to raise. Production asks for the
current year only, though, and none of these councils has papers up in the
first weeks of a year, so an empty *new* year must not raise: each would
otherwise show as failed every January until its first meeting.
"""

import json

import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.qld.etheridge import EtheridgeScraper
from aus_council_scrapers.scrapers.qld.lockhart_river import LockhartRiverScraper
from aus_council_scrapers.scrapers.qld.quilpie import QuilpieScraper
from aus_council_scrapers.scrapers.wa.three_springs import ThreeSpringsScraper
from aus_council_scrapers.scrapers.wa.west_arthur import WestArthurScraper
from aus_council_scrapers.scrapers.wa.wickepin import WickepinScraper
from aus_council_scrapers.scrapers.wa.wiluna import WilunaScraper
from tests.cassette import PlaybackFetcher, cassette_paths

SCRAPERS = {
    "etheridge": EtheridgeScraper,
    "lockhart_river": LockhartRiverScraper,
    "quilpie": QuilpieScraper,
    "three_springs": ThreeSpringsScraper,
    "west_arthur": WestArthurScraper,
    "wickepin": WickepinScraper,
    "wiluna": WilunaScraper,
}


class _BlankFetcher(Fetcher):
    """Every page loads, and none has anything on it: a redesigned site."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if "blob.core.windows.net" in url:
            return (
                '<?xml version="1.0"?><EnumerationResults><Blobs/></EnumerationResults>'
            )
        return "<html><body><p>Page moved</p></body></html>"

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")

    def close(self):
        pass


class _CassetteOr404(Fetcher):
    """The recorded site, with every page it never recorded answering 404.

    That is what a new year looks like before the council makes its page.
    """

    def __init__(self, slug: str):
        _, replay_path = cassette_paths(slug)
        with open(replay_path) as f:
            self._playback = PlaybackFetcher(json.load(f), slug)

    def fetch_with_requests(self, url, method="GET", **kwargs):
        try:
            return self._playback.fetch_with_requests(url, method, **kwargs)
        except BaseException as e:
            if type(e).__name__ != "CassetteMiss":
                raise
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(f"404 for {url}", response=response)

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")

    def sleep(self, seconds):
        pass

    def close(self):
        pass


def _run(slug: str, fetcher: Fetcher, today: str, year: int):
    scraper = SCRAPERS[slug]()
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(today):
        return scraper.scraper()


@pytest.mark.parametrize("slug", sorted(SCRAPERS))
def test_a_blank_site_raises(slug):
    with pytest.raises(RuntimeError):
        _run(slug, _BlankFetcher(), "2026-10-20", 2026)


@pytest.mark.parametrize("slug", sorted(SCRAPERS))
def test_an_empty_new_year_is_not_an_error_in_january(slug):
    # The recorded site as it stood in October 2026, run as if it were
    # January 2027: no 2027 page, menu entry or papers yet.
    assert _run(slug, _CassetteOr404(slug), "2027-01-10", 2027) == []


@pytest.mark.parametrize("slug", sorted(SCRAPERS))
def test_an_empty_year_is_an_error_by_april(slug):
    with pytest.raises((RuntimeError, requests.HTTPError)):
        _run(slug, _CassetteOr404(slug), "2027-04-15", 2027)


def _etheridge_year(year: int):
    _, replay_path = cassette_paths("etheridge")
    with open(replay_path) as f:
        playback = PlaybackFetcher(json.load(f), "etheridge")
    scraper = EtheridgeScraper()
    scraper.fetcher = playback
    scraper.years_filter = [year]
    with clock.frozen(playback.recorded_date):
        return scraper.scraper()


def test_etheridge_takes_the_day_the_papers_name_over_a_mistyped_card():
    # The December 2024 card says 11 December; the agenda's first page and
    # the minutes say 18 December.
    december = [r for r in _etheridge_year(2024) if r.date.startswith("2024-12")]
    assert [r.date for r in december] == ["2024-12-18"]
    assert december[0].webpage_url.endswith("/11th-December-2024")


def test_etheridge_reads_an_open_agenda_filed_under_a_closed_heading():
    may = next(r for r in _etheridge_year(2023) if r.date == "2023-05-17")
    assert may.agenda_url.endswith("/open_session_agenda___may_2023.pdf")
