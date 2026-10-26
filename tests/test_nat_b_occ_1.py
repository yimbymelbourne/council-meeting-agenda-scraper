"""OpenCitiesContentScraper: what a one-year run fetches, and what a failed
fetch does.

Cassettes are recorded unfiltered, so replay never sees production's shape:
one `--years` year a night. For the two councils whose papers span two
pages—Paroo (this year's page and a previous-years page) and Burdekin (an
archive and a latest-meeting page)—a year must fetch only the pages that can
hold it, and still return every meeting of that year.

And because a page is the whole of what it holds, losing one is losing those
meetings outright. A failed page must fail the council, not leave it looking
healthy with the other page's meetings.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BlockedByWAF
from aus_council_scrapers.scrapers.qld.burdekin import BurdekinScraper
from aus_council_scrapers.scrapers.qld.paroo import ParooScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_PAROO = "https://www.paroo.qld.gov.au/Council/Council-Publications/Council-Meetings"
_BURDEKIN = "https://www.burdekin.qld.gov.au/About-council/Council-meetings"


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug, refuse: str | None = None):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []
        self._refuse = refuse

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        if url == self._refuse:
            raise BlockedByWAF(url, "test")
        return super().fetch_with_requests(url, method, **kwargs)


def _playback(slug: str, refuse: str | None = None):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        fetcher = _CountingPlayback(json.load(f), slug, refuse)
    with open(result_path) as f:
        expected = json.load(f)
    return fetcher, expected


def _key(r: dict) -> tuple:
    return (r["date"], r["name"], r["agenda_url"] or "", r["minutes_url"] or "")


@pytest.mark.parametrize(
    "scraper_class, slug, year, pages",
    [
        (ParooScraper, "paroo", 2026, [f"{_PAROO}/Current-Year-Meetings"]),
        (ParooScraper, "paroo", 2023, [f"{_PAROO}/Previous-Years-Meetings"]),
        (
            BurdekinScraper,
            "burdekin",
            2026,
            [f"{_BURDEKIN}/Archived-agendas-and-minutes", _BURDEKIN],
        ),
        (
            BurdekinScraper,
            "burdekin",
            2021,
            [f"{_BURDEKIN}/Archived-agendas-and-minutes"],
        ),
    ],
)
def test_one_year_fetches_only_its_pages_and_keeps_its_meetings(
    scraper_class, slug, year, pages
):
    fetcher, expected = _playback(slug)
    scraper = scraper_class()
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    assert fetcher.requested == pages
    want = sorted(_key(r) for r in expected if parse_date(r["date"]).year == year)
    assert want, f"the {slug} cassette has no {year} meetings to compare"
    assert sorted(_key(r) for r in results) == want


def test_a_refused_page_fails_the_council():
    # The archive refused, the latest-meeting page served: returning that
    # one meeting would report Burdekin as working with a year's papers gone.
    fetcher, _ = _playback(
        "burdekin", refuse=f"{_BURDEKIN}/Archived-agendas-and-minutes"
    )
    scraper = BurdekinScraper()
    scraper.fetcher = fetcher
    scraper.years_filter = [2026]
    with clock.frozen(fetcher.recorded_date), pytest.raises(BlockedByWAF):
        scraper.scraper()


# --- a page the cassettes cannot show ----------------------------------------
#
# The next two cases are states no live page is in today: a page with no
# papers at all, and a January meeting still filed under December's year
# after it has passed. Both are about what the base does on the day it
# happens, so they run on a minimal page under a frozen clock.

from aus_council_scrapers.opencities_content import (  # noqa: E402
    ContentPage,
    OpenCitiesContentScraper,
)

_PAGE = "https://council.example/Council-Meetings"


class _Page:
    def __init__(self, html: str):
        self.html = html

    def fetch_with_requests(self, url, method="GET", **kwargs):
        assert url == _PAGE
        return self.html


class _OneCouncil(OpenCitiesContentScraper):
    pages = [ContentPage(_PAGE)]

    def __init__(self):
        super().__init__("example", "QLD", "https://council.example")


def _accordion(heading: str, links: list[tuple[str, str]]) -> str:
    items = "".join(f'<li><a href="{href}">{label}</a></li>' for label, href in links)
    return (
        '<div id="main-content"><div class="accordion-list-item-container">'
        f'<h2 class="item-text">{heading}</h2><ul>{items}</ul></div></div>'
    )


def test_a_page_with_no_papers_fails_rather_than_reporting_nothing():
    # An Akamai challenge or a redesigned page arrives as a 200 with no
    # /files/ links. Returning [] would read as a council with no meetings.
    scraper = _OneCouncil()
    scraper.fetcher = _Page('<div id="main-content"><p>Please wait</p></div>')
    scraper.years_filter = [2026]
    with clock.frozen("2026-10-20"), pytest.raises(RuntimeError):
        scraper.scraper()


def test_a_january_meeting_under_last_years_heading_keeps_its_year_once_past():
    scraper = _OneCouncil()
    scraper.fetcher = _Page(
        _accordion(
            "2026 Council Agendas",
            [
                (
                    "Ordinary Council Meeting - Agenda - 20 January 2027",
                    "/files/assets/public/v/1/2026/ordinary_agenda_20_january_2027.pdf",
                )
            ],
        )
    )
    scraper.years_filter = [2027]
    with clock.frozen("2027-01-21"):
        results = scraper.scraper()
    assert [r.date for r in results] == ["2027-01-20"]
