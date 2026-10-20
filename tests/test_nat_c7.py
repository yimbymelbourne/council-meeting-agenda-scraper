"""Wentworth, Upper Lachlan, Collie and East Arnhem fail loudly, and a
one-year run fetches only that year.

Replay pins what each scraper parses out of its recorded pages. It cannot
show two things production depends on:

- A failed fetch, or a page that has changed shape, must fail the council.
  Returning [] instead is reported as a working council with 0 meetings
  (the `okCouncils` blind spot in AGENTS.md).
- Production asks for one year. Upper Lachlan keeps 2017-2021 on a second
  page behind a 10 s crawl delay, and Collie has a page per year, so for
  those two the filter decides what is requested, not just what is returned.
  Cassettes are recorded unfiltered, so only a filtered replay checks it.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.upper_lachlan import UpperLachlanScraper
from aus_council_scrapers.scrapers.nsw.wentworth import WentworthScraper
from aus_council_scrapers.scrapers.nt.east_arnhem import EastArnhemScraper
from aus_council_scrapers.scrapers.wa.collie import CollieScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_SCRAPERS = [
    WentworthScraper,
    UpperLachlanScraper,
    CollieScraper,
    EastArnhemScraper,
]


class _Unreachable(Exception):
    pass


def _refuse(*args, **kwargs):
    raise _Unreachable("connection refused")


@pytest.mark.parametrize("scraper_class", _SCRAPERS)
def test_one_year_with_every_fetch_failing_raises(scraper_class, monkeypatch):
    scraper = scraper_class()
    scraper.years_filter = [2026]
    monkeypatch.setattr(scraper.fetcher, "fetch_with_requests", _refuse)
    with pytest.raises(_Unreachable):
        scraper.scraper()


@pytest.mark.parametrize("scraper_class", _SCRAPERS)
def test_a_page_with_no_meetings_layout_raises(scraper_class, monkeypatch):
    """A redesigned or placeholder page is not a council with no meetings."""
    scraper = scraper_class()
    scraper.years_filter = [2026]
    monkeypatch.setattr(
        scraper.fetcher,
        "fetch_with_requests",
        lambda *a, **k: "<html><body><p>This page has moved.</p></body></html>",
    )
    with pytest.raises(ValueError):
        scraper.scraper()


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _filtered_run(scraper_class, slug: str, year: int):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    recorded_date = next(v for k, v in replay if k == ["meta", "recorded_date"])

    scraper = scraper_class()
    scraper.fetcher = _CountingPlayback(replay, slug)
    scraper.years_filter = [year]
    with clock.frozen(recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    def key(m):
        return (m["date"], m["name"], m["agenda_url"] or "")

    wanted = sorted((m for m in expected if parse_date(m["date"]).year == year), key=key)
    assert wanted, f"the {slug} fixture has no {year} meetings to compare"
    assert sorted(results, key=key) == wanted
    return scraper.fetcher.requested


def test_upper_lachlan_reads_its_archive_only_for_years_it_holds():
    archive = "https://upperlachlan.nsw.gov.au/council/council-meetings/archives"
    assert archive not in _filtered_run(UpperLachlanScraper, "upper_lachlan", 2026)
    assert archive in _filtered_run(UpperLachlanScraper, "upper_lachlan", 2021)


def test_collie_fetches_only_the_wanted_years_page():
    requested = _filtered_run(CollieScraper, "collie", 2025)
    assert requested == [
        "https://www.collie.wa.gov.au/council/agendas-minutes-by-year/",
        "https://www.collie.wa.gov.au/2025-agendas-and-minutes/",
    ]


class _AttachmentPageDown(PlaybackFetcher):
    """The recorded pages, except one WordPress attachment page fails."""

    failing = "https://www.collie.wa.gov.au/0826-agenda/"

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url == self.failing:
            raise _Unreachable("connection refused")
        return super().fetch_with_requests(url, method, **kwargs)


def test_collie_raises_when_one_attachment_page_fails():
    """The index and the 2026 page load, but the 11 Aug 2026 agenda sits
    behind an attachment page that does not. Dropping that agenda would
    report a short list as a good scrape, and council-alerts would file the
    meeting under its minutes URL until the agenda came back."""
    _, replay_path = cassette_paths("collie")
    with open(replay_path) as f:
        replay = json.load(f)
    recorded_date = next(v for k, v in replay if k == ["meta", "recorded_date"])

    scraper = CollieScraper()
    scraper.fetcher = _AttachmentPageDown(replay, "collie")
    scraper.years_filter = [2026]
    with clock.frozen(recorded_date), pytest.raises(_Unreachable):
        scraper.scraper()
