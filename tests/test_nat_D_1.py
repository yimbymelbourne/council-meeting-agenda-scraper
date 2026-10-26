"""Southern Midlands, Narromine, Junee, Buloke, Central Desert, Torres Strait
Island and Gingin: what the cassette replay cannot see.

The replay is recorded unfiltered, so it never shows what one production year
costs, and it never shows a site that refuses us. Both matter in production:
the first is charged to the shared nightly budget, and the second, caught
and swallowed, reports a blocked council as one with no meetings.
"""

from __future__ import annotations

import json

import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.base import BlockedByWAF, Fetcher
from aus_council_scrapers.scrapers.nsw.junee import JuneeScraper
from aus_council_scrapers.scrapers.nsw.narromine import NarromineScraper
from aus_council_scrapers.scrapers.nt.central_desert import CentralDesertScraper
from aus_council_scrapers.scrapers.qld.torres_strait_island import (
    TorresStraitIslandScraper,
)
from aus_council_scrapers.scrapers.tas.southern_midlands import SouthernMidlandsScraper
from aus_council_scrapers.scrapers.vic.buloke import BulokeScraper
from aus_council_scrapers.scrapers.wa.gingin import GinginScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_YEAR = 2026

# The most requests one production year may cost, as designed: Southern
# Midlands reads its hub and the current-year page; Narromine and Central
# Desert one page; Junee its two pages; Buloke its index and one year page;
# Torres Strait Island one listing page per report type and a post per
# meeting; Gingin its year listing, three search requests, the upcoming page
# and two meeting pages.
_BUDGET = {
    SouthernMidlandsScraper: 2,
    NarromineScraper: 1,
    JuneeScraper: 2,
    BulokeScraper: 2,
    CentralDesertScraper: 1,
    TorresStraitIslandScraper: 12,
    GinginScraper: 8,
}


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _cassette(slug: str):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    return replay, expected


def _key(meeting: dict):
    return (meeting["date"], meeting["name"], meeting["agenda_url"] or "")


@pytest.mark.parametrize("scraper_class", list(_BUDGET), ids=lambda c: c.__name__)
def test_one_year_returns_that_year_within_budget(scraper_class):
    scraper = scraper_class()
    replay, expected = _cassette(scraper.council_name)
    fetcher = _CountingPlayback(replay, scraper.council_name)
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]

    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    assert sorted(results, key=_key) == sorted(
        (m for m in expected if m["date"].startswith(str(_YEAR))), key=_key
    )
    assert len(fetcher.requested) <= _BUDGET[scraper_class], fetcher.requested


class _RefusingFetcher(Fetcher):
    """Serves the given pages, and refuses every other URL with a 403."""

    def __init__(self, pages=None):
        self._pages = pages or {}

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if method == "GET" and url in self._pages:
            return self._pages[url]
        raise BlockedByWAF(url, "test")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")

    def close(self):
        pass


@pytest.mark.parametrize("scraper_class", list(_BUDGET), ids=lambda c: c.__name__)
def test_refused_site_raises(scraper_class):
    scraper = scraper_class()
    scraper.fetcher = _RefusingFetcher()
    scraper.years_filter = [_YEAR]
    with pytest.raises(BlockedByWAF):
        scraper.scraper()


def test_gingin_raises_when_the_search_is_refused():
    # Without the search, this year's minutes would go out under the file
    # store's versioned addresses, and every version bump would be a new
    # meeting downstream. The year listing loading is not enough.
    replay, _ = _cassette("gingin")
    playback = PlaybackFetcher(replay, "gingin")
    listing = "https://www.gingin.wa.gov.au/council-meetings/past/2026"
    scraper = GinginScraper()
    scraper.fetcher = _RefusingFetcher({listing: playback.fetch_with_requests(listing)})
    scraper.years_filter = [_YEAR]
    with clock.frozen(playback.recorded_date), pytest.raises(BlockedByWAF):
        scraper.scraper()


def _narromine_page(next_meeting: str) -> str:
    # October's meeting, dated by its minutes, keeps the year from being
    # empty, which would raise rather than return.
    return f"""
    <p>The next Council Meeting will be held on {next_meeting}.</p>
    <ul><li class="accordion-item">
      <a class="accordion-title" href="#">2026 October</a>
      <div class="accordion-content">
        <a href="/00.%20Minutes%2014.10.26.pdf">00. Minutes 14.10.26</a>
      </div>
    </li>
    <li class="accordion-item">
      <a class="accordion-title" href="#">2026 November</a>
      <div class="accordion-content">
        <a href="/01.%20Meeting%20Notice%20and%20Agenda%20-%20November%202026.pdf">
          01. Meeting Notice and Agenda - November 2026</a>
        <a href="/02.%20Mayoral%20Minute%20-%20November%202026.pdf">
          02. Mayoral Minute - November 2026</a>
      </div>
    </li></ul>
    """


@pytest.mark.parametrize(
    "next_meeting, expected_dates",
    [
        # The page announces this meeting: its agenda takes that day.
        ("Wednesday 11 November 2026", ["2026-11-11"]),
        # It announces some other month's meeting: no day is guessed.
        ("Wednesday 9 December 2026", []),
    ],
)
def test_narromine_dates_an_upcoming_agenda_only_from_the_page(
    next_meeting, expected_dates
):
    url = "https://www.narromine.nsw.gov.au/council/council-meetings"
    scraper = NarromineScraper()
    scraper.fetcher = _RefusingFetcher({url: _narromine_page(next_meeting)})
    scraper.years_filter = [_YEAR]
    with clock.frozen("2026-11-06"):
        results = [r for r in scraper.scraper() if r.agenda_url]
    assert [r.date for r in results] == expected_dates
    assert all(r.agenda_url.endswith("November%202026.pdf") for r in results)
    assert all("Mayoral" not in r.agenda_url for r in results)


class _NotFoundFetcher(_RefusingFetcher):
    """Serves the given pages, and answers every other URL with a 404."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if method == "GET" and url in self._pages:
            return self._pages[url]
        raise requests.HTTPError(f"404 for {url}")


def test_central_desert_raises_when_this_years_category_is_gone():
    # A site-wide move answers 404 for every category. Read as "no category
    # yet", that would be a successful night with no meetings.
    scraper = CentralDesertScraper()
    scraper.fetcher = _NotFoundFetcher()
    scraper.years_filter = [_YEAR]
    with clock.frozen("2026-10-20"), pytest.raises(requests.HTTPError):
        scraper.scraper()


def test_central_desert_reads_a_missing_new_year_as_empty_in_january():
    # Before the first meeting of a year, its category does not exist yet.
    scraper = CentralDesertScraper()
    scraper.fetcher = _NotFoundFetcher()
    scraper.years_filter = [2027]
    with clock.frozen("2027-01-10"):
        assert scraper.scraper() == []


def test_buloke_raises_when_the_index_lacks_this_year():
    # The index decides which years are requested; one that stops linking
    # the current year must not read as a year with no meetings.
    index = """
    <a href="/agendas-minutes-and-attachments-2025">2025</a>
    <a href="/agendas-minutes-and-attachments-2024">2024</a>
    """
    scraper = BulokeScraper()
    scraper.fetcher = _RefusingFetcher(
        {"https://www.buloke.vic.gov.au/agendas-minutes-attachments": index}
    )
    scraper.years_filter = [_YEAR]
    with clock.frozen("2026-10-20"), pytest.raises(RuntimeError):
        scraper.scraper()


@pytest.mark.parametrize(
    "label",
    [
        "NOTICE OF SPECIAL COUNCIL MEETING - 17 Oct 2025",
        "Special Mtg Papers - website copy",
    ],
)
def test_torres_takes_an_unnamed_special_agenda(label):
    # Three 2025 special meetings file their agenda under these labels; the
    # PDFs open with the agenda and order of business.
    post = "https://tsirc.qld.gov.au/documents/special-council-meeting-17-october-2025/"
    uploads = "https://tsirc.qld.gov.au/wp-content/uploads/2025/10"
    page = f"""
    <a href="{uploads}/notice.pdf">{label}</a>
    <a href="{uploads}/confirmed.pdf">CONFIRMED - Special Council Mtg - 17 Oct 2025</a>
    """
    scraper = TorresStraitIslandScraper()
    scraper.fetcher = _RefusingFetcher({post: page})
    assert scraper._papers(post) == (
        f"{uploads}/notice.pdf",
        f"{uploads}/confirmed.pdf",
    )


def test_gingin_emits_no_file_store_address():
    # robots.txt disallows the module file store, and council-alerts fetches
    # every document URL emitted, so none may point there.
    _, expected = _cassette("gingin")
    for meeting in expected:
        for key in ("agenda_url", "minutes_url", "download_url", "webpage_url"):
            assert "/moduledata/" not in (meeting[key] or "").lower(), meeting
