"""Brisbane reads two sources: minutes from the meetings page, agendas from
the council's document bucket. A run where a source fails and nothing comes
back must fail the council, not report it as ok with 0 meetings."""

import json

import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.qld.brisbane import BrisbaneScraper
from tests.cassette import PlaybackFetcher, cassette_paths


class _Failing(PlaybackFetcher):
    """Replays the recording, but fails any URL `fails` matches."""

    def __init__(self, replay, fails):
        super().__init__(replay, "brisbane")
        self._fails = fails

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if self._fails(url):
            raise requests.ConnectionError("unreachable")
        return super().fetch_with_requests(url, method, **kwargs)


def _meetings_page(url):
    return "www.brisbane.qld.gov.au" in url


def _year_folder(url):
    # The folder discovery query (with a delimiter) still answers; only the
    # listing of a year's folder fails.
    return "amazonaws.com" in url and "delimiter" not in url


def _run(fails):
    _, replay_path = cassette_paths("brisbane")
    with open(replay_path) as f:
        replay = json.load(f)
    fetcher = _Failing(replay, fails)
    scraper = BrisbaneScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [int(fetcher.recorded_date[:4])]
    with clock.frozen(fetcher.recorded_date):
        return scraper.scraper()


def test_meetings_page_and_year_folders_failing_fails_the_council():
    with pytest.raises(RuntimeError, match="neither"):
        _run(lambda url: _meetings_page(url) or _year_folder(url))


def test_one_source_failing_keeps_what_the_other_found():
    assert _run(_year_folder)
