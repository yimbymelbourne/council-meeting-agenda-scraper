"""Tasman's papers are matched by filename alone. If the council renames its
files, every paper drops out of the pattern; that must fail the council, not
report it as ok with 0 meetings."""

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.tas.tasman import TasmanScraper
from tests.cassette import PlaybackFetcher, cassette_paths


def _run(rename: bool, year_offset: int = 0):
    _, replay_path = cassette_paths("tasman")
    with open(replay_path) as f:
        replay = json.load(f)
    if rename:
        # "20260826-Council-Meeting-Agenda-August-2026.pdf" becomes
        # "20260826-Agenda-August-2026.pdf", and the same for minutes.
        replay = [
            [key, value.replace("-Council-Meeting-", "-") if isinstance(value, str) else value]
            for key, value in replay
        ]
    fetcher = PlaybackFetcher(replay, "tasman")
    scraper = TasmanScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [int(fetcher.recorded_date[:4]) + year_offset]
    with clock.frozen(fetcher.recorded_date):
        return scraper.scraper()


def test_renamed_papers_fail_the_council():
    with pytest.raises(RuntimeError, match="no papers matched"):
        _run(rename=True)


def test_a_past_year_is_empty_without_failing():
    # The page holds the current year only; earlier minutes are on request.
    assert _run(rename=False, year_offset=-1) == []
