"""The production fetch bound for CouncilConnect councils.

Cassettes are recorded unfiltered, so the replay test in scraper_test.py
proves the full history parses but says nothing about what one production
night costs. Production passes a single year, and on these sites most
meetings cost a request of their own, so a scraper that stopped honouring
`years_filter` would still pass replay while fetching seven years a night out
of the shared 600 s budget. This replays the same cassettes with the filter
production uses and checks both halves of the bargain: it fetches only that
year, and it still finds every meeting of that year.

The budget check covers only the recording year. Cottesloe pays a request per
meeting, and that year had 13; a 20-meeting year such as 2023 costs ~24, so
this test would not have caught that.
"""

import json
import re

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

# One production year should stay within ~20 requests (see AGENTS.md on the
# 600 s budget).
REQUEST_BUDGET = 20

# The file store's own address for a meeting document: the <ver> segment goes
# up whenever the council edits the meeting, so a URL with it changes from
# night to night and council-alerts, which keys meetings on agenda_url, would
# record the meeting again each time.
VERSIONED_DOCUMENT = re.compile(r"/moduledata/councilmeetings/[^/]+/\d+\.\d+/")


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize("class_name", ["CottesloeScraper", "EastFremantleScraper"])
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        fetcher = _Counting(json.load(f), scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)

    year = int(fetcher.recorded_date[:4])
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    try:
        with clock.frozen(fetcher.recorded_date):
            result = scraper.scraper()
    finally:
        del scraper.years_filter

    other_years = [
        u for u in fetcher.urls if "/past/" in u and f"/past/{year}" not in u
    ]
    assert other_years == []
    assert len(fetcher.urls) <= REQUEST_BUDGET
    assert [r.to_dict() for r in result] == [
        m for m in recorded if m["date"].startswith(str(year))
    ]


@pytest.mark.parametrize("class_name", ["CottesloeScraper", "EastFremantleScraper"])
def test_document_urls_carry_no_file_store_version(class_name):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, _ = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)

    versioned = [
        m[field]
        for m in recorded
        for field in ("agenda_url", "minutes_url", "download_url")
        if m[field] and VERSIONED_DOCUMENT.search(m[field])
    ]
    assert versioned == []
