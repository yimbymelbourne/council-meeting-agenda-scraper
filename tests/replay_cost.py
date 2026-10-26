"""Helpers for tests that replay a cassette with `years_filter` set and check
what the scraper asked for, not just what it returned.

Cassettes are recorded unfiltered, so the ordinary replay cannot see a scraper
that fetches every year's pages and lets `main.py` throw most of them away.
These tests replay the same recording with one year wanted and check both
halves: that year's meetings still come back, and the other years' pages are
never requested.
"""

from __future__ import annotations

import json

from dateutil.parser import parse as parse_date

from tests.cassette import PlaybackFetcher, cassette_paths


def load_cassette(slug: str) -> tuple[list, list[dict]]:
    """The slug's replay data and its expected results."""
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    return replay, expected


def recorded_date(replay: list) -> str:
    """The date the cassette was recorded, for `clock.frozen`."""
    return next(value for key, value in replay if key == ["meta", "recorded_date"])


def sorted_meetings(results) -> list[dict]:
    # Order is not the contract here; which meetings come back is.
    return sorted(results, key=lambda r: (r["date"], r["name"], r["agenda_url"] or ""))


def meetings_in(results: list[dict], year: int) -> list[dict]:
    return sorted_meetings(r for r in results if parse_date(r["date"]).year == year)


class CountingPlayback(PlaybackFetcher):
    """Playback that remembers which URLs the scraper asked for."""

    def __init__(self, replay_data, slug, driver=None):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []
        self._driver = driver

    def get_selenium_driver(self):
        return self._driver if self._driver else super().get_selenium_driver()

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        self.requested.append(url)
        return super().fetch_with_selenium(url, wait_time, wait_condition)

    def fetch_bytes(self, url, max_bytes=None, **kwargs):
        self.requested.append(url)
        return super().fetch_bytes(url, max_bytes, **kwargs)

    def fetch_pdf_text(self, url, *args, **kwargs):
        self.requested.append(url)
        return super().fetch_pdf_text(url, *args, **kwargs)
